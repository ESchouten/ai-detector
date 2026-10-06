import { Agent as HttpAgent } from 'node:http';
import { connect } from 'node:net';
import os from 'node:os';
import { Agent as HttpsAgent } from 'node:https';
import { promisify } from 'node:util';
import onvif from 'onvif';
import * as v from 'valibot';
import type { CameraConnectionInput, CameraProfile, DiscoveredCamera } from '../../cameras.ts';
import type { StreamMeta } from '../../schema.ts';
import {
	cameraAddress,
	cameraStream,
	CameraConnectionError,
	connectionFailure
} from './connection.ts';

const { Cam, Discovery } = onvif;

const probeReply = v.object({
	probeMatches: v.object({
		probeMatch: v.object({
			XAddrs: v.string(),
			scopes: v.optional(v.union([v.string(), v.object({ _: v.string() })]), '')
		})
	})
});
const mediaProfile = v.object({ $: v.object({ token: v.string() }), name: v.optional(v.string()) });

function cameraName(scopes: string, fallback: string): string {
	const prefix = 'onvif://www.onvif.org/name/';
	const name = scopes.split(/\s+/).find((scope) => scope.startsWith(prefix));
	if (!name) return fallback;
	try {
		return decodeURIComponent(name.slice(prefix.length)) || fallback;
	} catch {
		return fallback;
	}
}

export function discoveredCameras(replies: unknown[]): DiscoveredCamera[] {
	const cameras = new Map<string, DiscoveredCamera>();
	for (const reply of replies) {
		const parsed = v.safeParse(probeReply, reply);
		if (!parsed.success) continue;
		const match = parsed.output.probeMatches.probeMatch;
		for (const value of match.XAddrs.split(/\s+/)) {
			try {
				const address = cameraAddress(value);
				address.search = '';
				address.hash = '';
				const scopes = typeof match.scopes === 'string' ? match.scopes : match.scopes._;
				const name = cameraName(scopes, address.hostname);
				cameras.set(address.href, { address: address.href, name });
				break;
			} catch (cause) {
				// Discovery replies are external input; one malformed address must not hide other devices.
				if (!(cause instanceof CameraConnectionError)) throw cause;
			}
		}
	}
	return [...cameras.values()].sort((a, b) => a.name.localeCompare(b.name));
}

type CameraDiscovery = { cameras: DiscoveredCamera[]; message?: string };
let pendingDiscovery: Promise<CameraDiscovery> | undefined;

export function discoverCameras(): Promise<CameraDiscovery> {
	pendingDiscovery ??= scanCameras().finally(() => {
		pendingDiscovery = undefined;
	});
	return pendingDiscovery;
}

/** This computer's addresses on its networks, by connection. */
function localAddresses(): { connection: string; address: string }[] {
	return Object.entries(os.networkInterfaces()).flatMap(([connection, addresses]) =>
		(addresses ?? [])
			.filter(({ family, internal }) => family === /* @wc-ignore */ 'IPv4' && !internal)
			.map(({ address }) => ({ connection, address }))
	);
}

/** Ask every camera on one connection to announce itself; a computer often has several. */
function probe(connection: string): Promise<unknown[]> {
	return new Promise((resolve) => {
		Discovery.probe({ device: connection, resolve: false, timeout: 5000 }, (_error, devices) => {
			// Socket errors call back early; the SDK still closes its socket and returns devices at the deadline.
			if (devices) resolve(devices);
		});
	});
}

/** The ports cameras and recorders serve ONVIF on: the standard one, then Reolink's and other makers' own. */
const ONVIF_PORTS = [80, 8000, 8080, 2020, 8899];
const DATE_REQUEST =
	'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body><GetSystemDateAndTime xmlns="http://www.onvif.org/ver10/device/wsdl"/></s:Body></s:Envelope>';

function open(host: string, port: number): Promise<boolean> {
	return new Promise((resolve) => {
		const socket = connect({ host, port, timeout: 500 });
		const done = (result: boolean) => {
			socket.destroy();
			resolve(result);
		};
		socket.once('connect', () => done(true));
		socket.once('timeout', () => done(false));
		socket.once('error', () => done(false));
	});
}

/** Whether an address answers the one ONVIF question that needs no login. */
async function speaksOnvif(address: string): Promise<boolean> {
	try {
		const response = await fetch(address, {
			method: 'POST',
			headers: { 'Content-Type': 'application/soap+xml; charset=utf-8' },
			body: DATE_REQUEST,
			signal: AbortSignal.timeout(2000)
		});
		return (await response.text()).includes('GetSystemDateAndTimeResponse');
	} catch {
		return false;
	}
}

/**
 * The cameras among some addresses, found by asking each one directly. Announcements do not
 * get through on every network: a firewall may drop them, and some cameras never answer the
 * call, while they do answer when spoken to.
 */
export async function camerasAt(hosts: string[], ports = ONVIF_PORTS): Promise<DiscoveredCamera[]> {
	const found = await Promise.all(
		hosts.map(async (host) => {
			for (const port of ports) {
				const address = `http://${host}${port === 80 ? '' : `:${port}`}/onvif/device_service`;
				if ((await open(host, port)) && (await speaksOnvif(address)))
					return { address, name: host };
			}
		})
	);
	return found.filter((camera) => camera !== undefined);
}

/** The other addresses of a home or farm network this computer is on. */
export function neighbours(address: string): string[] {
	if (!/^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(address)) return [];
	const network = address.slice(0, address.lastIndexOf('.'));
	return Array.from({ length: 254 }, (_, index) => `${network}.${index + 1}`).filter(
		(host) => host !== address
	);
}

async function scanCameras(): Promise<CameraDiscovery> {
	let incomplete = false;
	const onError = () => {
		incomplete = true;
	};
	Discovery.on('error', onError);
	try {
		const local = localAddresses();
		const [announced, asked] = await Promise.all([
			Promise.all(local.map(({ connection }) => probe(connection))),
			camerasAt(local.flatMap(({ address }) => neighbours(address)))
		]);
		const cameras = discoveredCameras(announced.flat());
		const known = new Set(cameras.map(({ address }) => new URL(address).hostname));
		cameras.push(...asked.filter(({ address }) => !known.has(new URL(address).hostname)));
		return {
			cameras,
			message: incomplete
				? 'Camera search was incomplete. Check local network access, or enter a stream URL manually.'
				: cameras.length === 0
					? 'No cameras found. Check that this computer and camera use the same network and allow local network access, or enter its stream URL manually.'
					: undefined
		};
	} finally {
		Discovery.off('error', onError);
	}
}

export async function resolveCameraStream(
	input: CameraConnectionInput
): Promise<{ source: string; profiles: CameraProfile[]; connection?: StreamMeta['connection'] }> {
	if (input.streamUri)
		return { source: cameraStream(input.streamUri, input.username, input.password), profiles: [] };
	const address = cameraAddress(input.address);
	const secure = address.protocol === 'https:';
	const agent = secure ? new HttpsAgent() : new HttpAgent();
	const camera = new Cam({
		hostname: address.hostname,
		port: Number(address.port || (secure ? 443 : 80)),
		path: address.pathname === '/' ? '/onvif/device_service' : address.pathname,
		username: input.username,
		password: input.password,
		useSecure: secure,
		timeout: 7000,
		autoconnect: false,
		agent
	});
	let responseStatus = 0;
	camera.on('rawResponse', (_xml, status) => {
		responseStatus = status;
	});
	try {
		// Read stream profiles without configuring the SDK's active/PTZ source state.
		await promisify(camera.getSystemDateAndTime.bind(camera))();
		try {
			await promisify(camera.getServices.bind(camera))();
		} catch {
			// Older ONVIF cameras expose capabilities instead of the services operation.
			await promisify(camera.getCapabilities.bind(camera))();
		}
		await promisify(camera.getProfiles.bind(camera))();
		const profiles = (camera.profiles ?? []).flatMap((profile) => {
			const parsed = v.safeParse(mediaProfile, profile);
			return parsed.success
				? [
						{
							token: parsed.output.$.token,
							name: parsed.output.name ?? `Camera ${parsed.output.$.token}`
						}
					]
				: [];
		});
		if (!profiles.length)
			throw new CameraConnectionError(
				'This device did not provide a video stream. Check that camera streaming is enabled or enter its stream URL manually.'
			);
		const selected = input.profileToken ?? profiles[0].token;
		if (!profiles.some((profile) => profile.token === selected))
			throw new CameraConnectionError(
				'That camera channel is no longer available. Connect again and choose a channel.'
			);
		const stream = await new Promise<{ uri: string }>((resolve, reject) => {
			camera.getStreamUri({ protocol: 'RTSP', profileToken: selected }, (error, result) => {
				if (error) reject(error);
				else if (!result?.uri)
					reject(new CameraConnectionError('The camera did not return a stream address.'));
				else resolve(result);
			});
		});
		return {
			source: cameraStream(stream.uri, input.username, input.password),
			profiles,
			connection: { address: `${address.origin}${address.pathname}`, profileToken: selected }
		};
	} catch (cause) {
		if (cause instanceof CameraConnectionError) throw cause;
		// The SDK's clock-authentication retry can replace a 401 with an XML parsing error.
		if (responseStatus === 401 || responseStatus === 403)
			throw connectionFailure(`HTTP ${responseStatus}`);
		throw connectionFailure(cause);
	} finally {
		agent.destroy();
	}
}

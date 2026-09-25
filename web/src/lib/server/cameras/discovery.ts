import { Agent as HttpAgent } from 'node:http';
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

async function scanCameras(): Promise<CameraDiscovery> {
	let incomplete = false;
	const onError = () => {
		incomplete = true;
	};
	Discovery.on('error', onError);
	try {
		const devices = await new Promise<unknown[]>((resolve) => {
			Discovery.probe({ resolve: false, timeout: 5000 }, (_error, devices) => {
				// Socket errors call back early; the SDK still closes its socket and returns devices at the deadline.
				if (devices) resolve(devices);
			});
		});
		const cameras = discoveredCameras(devices);
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

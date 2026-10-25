import { execFile } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { promisify } from 'node:util';
import type { CameraDevice, StreamMeta } from '../../schema.ts';
import { movedSource } from './connection.ts';
import { localAddresses, neighbours, onvifCamera, open } from './discovery.ts';

const execute = promisify(execFile);

/** A MAC address written as aa:bb:cc:dd:ee:ff. macOS leaves out leading zeros, Windows uses dashes. */
export function macAddress(value: string | undefined): string | undefined {
	const parts = value?.trim().toLowerCase().split(/[:-]/) ?? [];
	if (parts.length !== 6 || !parts.every((part) => /^[0-9a-f]{1,2}$/.test(part))) return undefined;
	const mac = parts.map((part) => part.padStart(2, '0')).join(':');
	// An address the computer asked for and never heard back from, or the broadcast address.
	return mac === '00:00:00:00:00:00' || mac === 'ff:ff:ff:ff:ff:ff' ? undefined : mac;
}

/**
 * The devices the computer has spoken to on its networks, by address, from the neighbour (ARP)
 * table as Linux, macOS and Windows write it.
 */
export function neighbourTable(text: string): Map<string, string> {
	const table = new Map<string, string>();
	for (const line of text.split('\n')) {
		const address = line.match(/(?:^|[\s(])(\d{1,3}(?:\.\d{1,3}){3})(?=[\s)])/)?.[1];
		const mac = macAddress(
			line.match(/(?:^|\s)([0-9a-f]{1,2}(?:[:-][0-9a-f]{1,2}){5})(?=\s|$)/i)?.[1]
		);
		if (address && mac) table.set(address, mac);
	}
	return table;
}

async function readNeighbours(): Promise<Map<string, string>> {
	try {
		if (process.platform === 'linux')
			return neighbourTable(await readFile('/proc/net/arp', 'utf8'));
		const args = process.platform === 'win32' ? ['-a'] : ['-an'];
		const { stdout } = await execute('arp', args, { timeout: 5000, windowsHide: true });
		return neighbourTable(stdout);
	} catch {
		return new Map();
	}
}

/** Whether a host is on a network this computer is on itself, where its MAC address is seen. */
function nearby(host: string): boolean {
	return localAddresses().some(({ address }) => neighbours(address).includes(host));
}

/** The port a camera streams on, which any reply to fills the computer's neighbour table. */
function streamPort(source: URL): number {
	if (source.port) return Number(source.port);
	return { 'rtsp:': 554, 'rtsps:': 322, 'https:': 443 }[source.protocol] ?? 80;
}

function xmlValue(xml: string, name: string): string | undefined {
	return xml.match(new RegExp(`<(?:[\\w-]+:)?${name}>([^<]*)</`))?.[1]?.trim() || undefined;
}

function ask(
	call: (callback: (error: Error | null, data?: unknown, xml?: string) => void) => void
) {
	return new Promise<string>((resolve, reject) =>
		call((error, _data, xml) => (error ? reject(error) : resolve(xml ?? '')))
	);
}

/** The serial number and MAC address an ONVIF device gives of itself, as far as it gives them. */
export async function onvifIdentity(
	address: string,
	username: string,
	password: string
): Promise<CameraDevice> {
	const { camera, agent } = onvifCamera(new URL(address), username, password);
	try {
		await promisify(camera.getSystemDateAndTime.bind(camera))();
		// The SDK turns a serial number of digits into a number; the reply itself keeps it exact.
		const information = await ask((callback) => camera.getDeviceInformation(callback));
		// The network settings are asked of the device service, which the SDK must first find.
		const interfaces = await promisify(camera.getServices.bind(camera))()
			.catch(() => promisify(camera.getCapabilities.bind(camera))())
			.then(() => ask((callback) => camera.getNetworkInterfaces(callback)))
			.catch(() => '');
		const serial = xmlValue(information, 'SerialNumber');
		const mac = macAddress(xmlValue(interfaces, 'HwAddress'));
		return { ...(serial ? { serial } : {}), ...(mac ? { mac } : {}) };
	} catch {
		return {};
	} finally {
		agent.destroy();
	}
}

function login(source: URL) {
	return {
		username: decodeURIComponent(source.username),
		password: decodeURIComponent(source.password)
	};
}

/**
 * What tells a camera apart when its address changes: the MAC address the computer sees it at,
 * and the serial number it gives over ONVIF. Undefined when neither is known.
 */
export async function learnDevice(camera: StreamMeta): Promise<CameraDevice | undefined> {
	let source: URL;
	try {
		source = new URL(camera.source);
	} catch {
		return undefined;
	}
	const { username, password } = login(source);
	const given = camera.connection
		? await onvifIdentity(camera.connection.address, username, password)
		: {};
	let seen: string | undefined;
	if (nearby(source.hostname)) {
		await open(source.hostname, streamPort(source));
		seen = (await readNeighbours()).get(source.hostname);
	}
	// What the computer sees at the address is the camera itself; a recorder may list several cards.
	const device: CameraDevice = { ...given, ...(seen ? { mac: seen } : {}) };
	return device.mac || device.serial ? device : undefined;
}

export interface CameraMove {
	id: string;
	/** The camera's source where it was lost. */
	source: string;
	/** The address it was found at. */
	host: string;
}

/**
 * The cameras among `lost` that answer at another address of this computer's networks, found by
 * their MAC address or, failing that, by their ONVIF serial number. A camera found at two
 * addresses, or at none, stays where it is.
 */
export async function locateCameras(lost: StreamMeta[]): Promise<CameraMove[]> {
	const cameras = lost.flatMap((camera) => {
		try {
			return camera.id && camera.device
				? [{ camera, id: camera.id, device: camera.device, source: new URL(camera.source) }]
				: [];
		} catch {
			return [];
		}
	});
	if (!cameras.length) return [];
	const hosts = [...new Set(localAddresses().flatMap(({ address }) => neighbours(address)))];
	const ports = [...new Set(cameras.map(({ source }) => streamPort(source)))];
	// Speaking to every address fills the neighbour table, and tells which ones stream at all.
	const answered = new Set<string>();
	await Promise.all(
		hosts.flatMap((host) =>
			ports.map(async (port) => {
				if (await open(host, port)) answered.add(host);
			})
		)
	);
	const table = await readNeighbours();
	const moves = await Promise.all(
		cameras.map(async ({ camera, id, device, source }) => {
			let found = device.mac
				? [...table].filter(([, mac]) => mac === device.mac).map(([host]) => host)
				: [];
			if (!found.length && device.serial && camera.connection) {
				const { username, password } = login(source);
				const address = camera.connection.address;
				const candidates = [...answered].filter((host) => host !== source.hostname);
				const serials = await Promise.all(
					candidates.map(
						async (host) =>
							(await onvifIdentity(movedSource(address, host), username, password)).serial
					)
				);
				found = candidates.filter((_, index) => serials[index] === device.serial);
			}
			// The old address can keep the camera's entry for a while after it moved.
			const elsewhere = found.filter((host) => host !== source.hostname);
			return elsewhere.length === 1 ? { id, source: camera.source, host: elsewhere[0] } : undefined;
		})
	);
	return moves.filter((move) => move !== undefined);
}

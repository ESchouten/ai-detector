import * as v from 'valibot';
import { plural } from './format.ts';

export const cameraConnectionInput = v.object({
	address: v.optional(v.pipe(v.string(), v.trim()), ''),
	username: v.optional(v.string(), ''),
	password: v.optional(v.string(), ''),
	streamUri: v.optional(v.pipe(v.string(), v.trim()), ''),
	profileToken: v.optional(v.string())
});

export type CameraConnectionInput = v.InferOutput<typeof cameraConnectionInput>;

/** The username in a saved camera's stream address, to start from when its login is changed. */
export function cameraUsername(source: string): string {
	try {
		return decodeURIComponent(new URL(source).username);
	} catch {
		return '';
	}
}

/** The cameras a detector watches, by name: "2 cameras · Barn, Yard". */
export function cameraSummary(sources: string[], cameras: { source: string; label?: string }[]) {
	const names = sources.map(
		(source) => cameras.find((camera) => camera.source === source)?.label ?? 'Custom source'
	);
	return `${plural(names.length, ['# camera', '# cameras'])} · ${names.join(', ')}`;
}

export interface DiscoveredCamera {
	address: string;
	name: string;
}

export interface CameraProfile {
	token: string;
	name: string;
}

export interface CameraConnectionResult {
	source: string;
	checkId: string;
	previewUrl: string;
}

/** Check what a camera shows: the check reports the source that worked, which is the one to save. */
export async function checkCameraPicture(
	source: string,
	signal: AbortSignal,
	endpoint: string
): Promise<CameraConnectionResult> {
	const response = await fetch(endpoint, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ source }),
		signal
	});
	if (!response.ok) {
		if (response.status === 400 || response.status === 403) {
			const { message } = await response.json();
			throw new Error(message);
		}
		throw new Error('The camera check could not finish. Please try again.');
	}
	return response.json();
}

/** Check the picture of a camera that answered. */
export async function checkConnection<T extends { source: string }>(
	connection: T,
	signal: AbortSignal,
	endpoint: string
): Promise<T & { check: CameraConnectionResult }> {
	signal.throwIfAborted();
	const check = await checkCameraPicture(connection.source, signal, endpoint);
	return { ...connection, source: check.source, check };
}

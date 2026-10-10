import * as v from 'valibot';

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

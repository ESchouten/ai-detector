import * as v from 'valibot';

export const cameraConnectionInput = v.object({
	address: v.optional(v.pipe(v.string(), v.trim()), ''),
	username: v.optional(v.string(), ''),
	password: v.optional(v.string(), ''),
	streamUri: v.optional(v.pipe(v.string(), v.trim()), ''),
	profileToken: v.optional(v.string())
});

export type CameraConnectionInput = v.InferOutput<typeof cameraConnectionInput>;

/** Keep setup drafts free of pasted logins and URL tokens. */
export function cameraDraftAddress(value: string): string | undefined {
	try {
		const address = new URL(value.includes('://') ? value : `http://${value}`);
		if (
			!['http:', 'https:'].includes(address.protocol) ||
			address.username ||
			address.password ||
			address.search ||
			address.hash
		)
			return undefined;
		return value;
	} catch {
		return undefined;
	}
}

/** Fill editable fields from saved server data, without putting credentials into draft storage. */
export function cameraEditConnection(source: string): { username: string; streamUri: string } {
	try {
		const stream = new URL(source);
		const username = decodeURIComponent(stream.username);
		stream.username = '';
		stream.password = '';
		return { username, streamUri: stream.toString() };
	} catch {
		return { username: '', streamUri: '' };
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
	checkedAt: string;
	previewUrl: string;
	recordingUrl: string;
	profiles: CameraProfile[];
}

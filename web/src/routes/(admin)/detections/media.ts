import { resolve } from '$app/paths';
import type { Detection } from '$lib/detections';

/** Media keeps its original archive location, whatever the current review says. */
export function recordingMedia(
	entry: Pick<Detection, 'type' | 'archiveStage' | 'timestamp'>,
	resource: 'best.jpg' | 'video.mp4'
): string {
	return resolve(
		`/detections/${[entry.type, entry.archiveStage, entry.timestamp, resource].map(encodeURIComponent).join('/')}`
	);
}

export function categoryName(type: string): string {
	return type.charAt(0).toUpperCase() + type.slice(1);
}

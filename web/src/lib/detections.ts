import type { Metadata, Stage } from './schema.ts';

/** The archive location is authoritative, even for older metadata documents. */
export interface Detection extends Metadata {
	stage: Stage;
	validation_error?: string | null;
}

export interface DetectionPage {
	items: Detection[];
	hasMore: boolean;
	nextOffset: number;
}

export interface DetectionFilter {
	type?: string;
	stage?: Stage;
	offset: number;
	limit: number;
}

export function detectionKey(detection: Detection): string {
	return JSON.stringify([detection.type, detection.stage, detection.timestamp]);
}

/** New recordings can shift offset pages; keep each archive entry once. */
export function mergeDetections(current: Detection[], incoming: Detection[]): Detection[] {
	return [
		...new Map([...current, ...incoming].map((entry) => [detectionKey(entry), entry])).values()
	];
}

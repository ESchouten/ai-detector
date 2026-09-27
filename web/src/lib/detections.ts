import type { Configuration, Metadata, Stage } from './schema.ts';
import { STAGES } from './schema.ts';
import * as v from 'valibot';

export function isArchiveSegment(value: string): boolean {
	return value.length > 0 && value !== '.' && value !== '..' && !/[/\\\0]/.test(value);
}

const calendarDate = v.pipe(
	v.string(),
	v.isoDate('Enter a date in YYYY-MM-DD format.'),
	v.check((value) => new Date(value).toJSON()?.slice(0, 10) === value, 'Enter a valid date.')
);

export const recordingExportInput = v.pipe(
	v.object({
		type: v.optional(v.pipe(v.string(), v.check(isArchiveSegment, 'Invalid category.'))),
		stage: v.optional(v.picklist(STAGES)),
		from: v.optional(calendarDate),
		to: v.optional(calendarDate)
	}),
	v.check(
		({ from, to }) => !from || !to || from <= to,
		'The end date must be on or after the start date.'
	)
);

export type RecordingExportFilter = v.InferOutput<typeof recordingExportInput>;

/** Color archived categories from their configured preset without storing extra metadata. */
export function recordingPresets({ config, app }: Configuration): Record<string, string> {
	const categories = new Map<string, Set<string>>();
	for (const [index, detector] of config.detectors.entries()) {
		for (const disk of detector.exporters?.disk ?? []) {
			if (!disk.directory) continue;
			const presets = categories.get(disk.directory) ?? new Set<string>();
			presets.add(app.detectors[index].preset ?? disk.directory);
			categories.set(disk.directory, presets);
		}
	}
	return Object.fromEntries(
		Array.from(categories, ([directory, presets]) => [
			directory,
			presets.size === 1 ? [...presets][0] : directory
		])
	);
}

/** The archive location is authoritative, even for older metadata documents. */
export interface Detection extends Metadata {
	type: string;
	stage: Stage;
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

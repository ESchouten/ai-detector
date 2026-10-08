import type { Configuration, Metadata, Stage } from './schema.ts';
import { STAGES } from './schema.ts';
import * as v from 'valibot';

/** How each outcome reads to the people reviewing recordings. */
export function stageLabel(stage: Stage): string {
	if (stage === 'approved') return 'Confirmed';
	return stage === 'rejected' ? 'False alarm' : 'Unreviewed';
}

export function isArchiveSegment(value: string): boolean {
	return value.length > 0 && value !== '.' && value !== '..' && !/[/\\\0]/.test(value);
}

const calendarDate = v.pipe(
	v.string(),
	v.isoDate(() => 'Enter a date in YYYY-MM-DD format.'),
	v.check(
		(value) => new Date(value).toJSON()?.slice(0, 10) === value,
		() => 'Enter a valid date.'
	)
);

export const recordingExportInput = v.pipe(
	v.object({
		type: v.optional(
			v.pipe(
				v.string(),
				v.check(isArchiveSegment, () => 'Invalid category.')
			)
		),
		stage: v.optional(v.picklist(STAGES)),
		from: v.optional(calendarDate),
		to: v.optional(calendarDate),
		/** Only the picture without boxes and the event's details, to share for training a model. */
		content: v.optional(v.literal('photos'))
	}),
	v.check(
		({ from, to }) => !from || !to || from <= to,
		() => 'The end date must be on or after the start date.'
	)
);

export type RecordingExportFilter = v.InferOutput<typeof recordingExportInput>;

export const manualReviewSchema = v.object({
	validated: v.boolean(),
	source: v.picklist(['web', 'telegram']),
	reviewed_at: v.pipe(v.string(), v.isoTimestamp())
});
export type ManualReview = v.InferOutput<typeof manualReviewSchema>;

export function reviewedStage(archiveStage: Stage, review: ManualReview | null): Stage {
	return review ? (review.validated ? 'approved' : 'rejected') : archiveStage;
}

export const reviewDetectionInput = v.object({
	type: v.pipe(v.string(), v.check(isArchiveSegment)),
	archiveStage: v.picklist(STAGES),
	timestamp: v.pipe(v.string(), v.check(isArchiveSegment)),
	validated: v.nullable(v.boolean())
});

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

/** Manual review overrides classification; media keeps its original archive location. */
export interface Detection extends Metadata {
	type: string;
	stage: Stage;
	archiveStage: Stage;
	review: ManualReview | null;
}

export interface DetectionPage {
	items: Detection[];
	hasMore: boolean;
	nextOffset: number;
	warnings?: string[];
}

export interface DetectionFilter {
	type?: string;
	stage?: Stage;
	offset: number;
	limit: number;
}

export interface Verdict {
	tone: 'ok' | 'neutral' | 'warn';
	label: string;
	/** Who decided: the validator, or a person here or in Telegram. */
	source: string;
	detail?: string;
}

/** The outcome shown on a recording; unreviewed recordings have none. */
export function recordingVerdict(
	entry: Pick<Detection, 'stage' | 'review' | 'validation_error'>
): Verdict | null {
	if (!entry.review && entry.validation_error)
		return {
			tone: 'warn',
			label: 'AI check failed',
			source: 'Not checked',
			detail: entry.validation_error
		};
	if (entry.stage === 'unvalidated') return null;
	return {
		tone: entry.stage === 'approved' ? 'ok' : 'neutral',
		label: stageLabel(entry.stage),
		source: !entry.review
			? 'Checked by AI'
			: entry.review.source === 'telegram'
				? 'Reviewed in Telegram'
				: 'Reviewed by you'
	};
}

/** The individuals recognised in a recording, as they are named on the Herd page. */
export function recordingNames(entry: Pick<Detection, 'identities'>): string {
	return (entry.identities ?? []).flatMap(({ name }) => name ?? []).join(', ');
}

export function detectionKey(
	detection: Pick<Detection, 'type' | 'archiveStage' | 'timestamp'>
): string {
	return JSON.stringify([detection.type, detection.archiveStage, detection.timestamp]);
}

/** New recordings can shift offset pages; keep each archive entry once. */
export function mergeDetections(current: Detection[], incoming: Detection[]): Detection[] {
	return [
		...new Map([...current, ...incoming].map((entry) => [detectionKey(entry), entry])).values()
	];
}

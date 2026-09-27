import { query } from '$app/server';
import * as v from 'valibot';
import { STAGES } from '$lib/schema';
import { DETECTIONS_DIR } from '$lib/server/application-paths';
import { DetectionArchive, isArchiveSegment } from '$lib/server/archive';
import { configuration } from '$lib/server/configuration';
import { recordingPresets, recordingExportInput } from '$lib/detections';

const archive = new DetectionArchive(DETECTIONS_DIR);

export const getTypes = query(() => archive.types());
export const getRecordingPresets = query(async () => recordingPresets(await configuration.read()));
export const getExportCount = query(
	recordingExportInput,
	async (filter) => (await archive.locations(filter)).length
);

export const getDetectionPage = query(
	v.object({
		type: v.optional(v.pipe(v.string(), v.check(isArchiveSegment))),
		stage: v.optional(v.picklist(STAGES)),
		offset: v.pipe(v.number(), v.integer(), v.minValue(0)),
		limit: v.pipe(v.number(), v.integer(), v.minValue(1), v.maxValue(100))
	}),
	(filter) => archive.page(filter)
);

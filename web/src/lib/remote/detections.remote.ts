import { query } from '$app/server';
import * as v from 'valibot';
import { STAGES } from '$lib/schema';
import { DETECTIONS_DIR } from '$lib/server/application-paths';
import { DetectionArchive, isArchiveSegment } from '$lib/server/archive';

const archive = new DetectionArchive(DETECTIONS_DIR);

export const getTypes = query(() => archive.types());

export const getDetectionPage = query(
	v.object({
		type: v.optional(v.pipe(v.string(), v.check(isArchiveSegment))),
		stage: v.optional(v.picklist(STAGES)),
		offset: v.pipe(v.number(), v.integer(), v.minValue(0)),
		limit: v.pipe(v.number(), v.integer(), v.minValue(1), v.maxValue(100))
	}),
	(filter) => archive.page(filter)
);

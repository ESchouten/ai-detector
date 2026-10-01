import { command, query } from '$app/server';
import * as v from 'valibot';
import { STAGES } from '$lib/schema';
import { isArchiveSegment } from '$lib/server/archive';
import { recordings as archive } from '$lib/server/recordings';
import { configuration } from '$lib/server/configuration';
import { recordingPresets, recordingExportInput, reviewDetectionInput } from '$lib/detections';

export const reviewDetection = command(reviewDetectionInput, ({ validated, ...address }) =>
	archive.review(address, validated, 'web')
);

export const getDetectionReviews = query(
	v.pipe(v.array(v.omit(reviewDetectionInput, ['validated'])), v.maxLength(100)),
	(addresses) =>
		Promise.all(
			addresses.map(async (address) => ({ ...address, review: await archive.readReview(address) }))
		)
);

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

import { command, query } from '$app/server';
import * as v from 'valibot';
import { recordings as archive } from '$lib/server/recordings';
import { configuration } from '$lib/server/configuration';
import {
	detectionFilterInput,
	recordingPresets,
	recordingExportInput,
	reviewDetectionInput
} from '$lib/detections';

export const reviewDetection = command(reviewDetectionInput, ({ validated, ...address }) =>
	archive.review(address, validated, 'web')
);

export const removeDetection = command(v.omit(reviewDetectionInput, ['validated']), (address) =>
	archive.remove(address)
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

export const getDetectionPage = query(detectionFilterInput, (filter) => archive.page(filter));

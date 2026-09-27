import { error } from '@sveltejs/kit';
import * as v from 'valibot';
import type { RequestHandler } from './$types';
import { recordingExportInput } from '$lib/detections';
import { DetectionArchive } from '$lib/server/archive';
import { DETECTIONS_DIR } from '$lib/server/application-paths';
import { exportRecordings } from '$lib/server/recording-export';

export const GET: RequestHandler = ({ url, request }) => {
	const parsed = v.safeParse(recordingExportInput, Object.fromEntries(url.searchParams));
	if (!parsed.success) error(400, parsed.issues[0].message);
	return exportRecordings(new DetectionArchive(DETECTIONS_DIR), parsed.output, request);
};

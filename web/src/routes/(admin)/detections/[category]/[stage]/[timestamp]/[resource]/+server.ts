import type { RequestHandler } from './$types';
import { DETECTIONS_DIR } from '$lib/server/application-paths';
import { archiveMedia } from '$lib/server/archive-media';

export const GET: RequestHandler = ({ params, request }) =>
	archiveMedia(DETECTIONS_DIR, params, request);
export const HEAD = GET;

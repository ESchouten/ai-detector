import type { RequestHandler } from './$types';
import { DATA_DIRECTORY } from '$lib/server/application-paths';
import { managedDetector } from '$lib/server/detector-service';
import { diagnosticFiles } from '$lib/server/diagnostics';
import { zipDownload } from '$lib/server/zip-download';
import { webLog } from '$lib/server/web-log';

export const GET: RequestHandler = async ({ request }) => {
	await managedDetector()?.log.flush();
	await webLog.flush();
	return zipDownload(
		'AI-Detector-diagnostics.zip',
		diagnosticFiles(DATA_DIRECTORY, managedDetector()?.status()),
		request
	);
};

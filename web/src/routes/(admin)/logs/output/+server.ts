import { createHash } from 'node:crypto';
import path from 'node:path';
import type { RequestHandler } from './$types';
import { DATA_DIRECTORY } from '$lib/server/application-paths';
import { managedDetector } from '$lib/server/detector-service';
import { readLogTail } from '$lib/server/detector-log';
import { webLog } from '$lib/server/web-log';

export const GET: RequestHandler = async ({ request }) => {
	const detector = managedDetector();
	const detectorText = detector
		? await detector.log.read()
		: await readLogTail(path.join(DATA_DIRECTORY, 'logs', 'detector.log'));
	const text = [detectorText, await webLog.read()]
		.filter(Boolean)
		.join('\n--- Web application ---\n');
	const etag = `"${createHash('sha256').update(text).digest('hex')}"`;
	const headers = {
		'Content-Type': 'text/plain; charset=utf-8',
		'Cache-Control': 'private, no-cache',
		ETag: etag
	};
	return request.headers.get('If-None-Match') === etag
		? new Response(null, { status: 304, headers })
		: new Response(text, { headers });
};

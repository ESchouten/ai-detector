import { createHash } from 'node:crypto';
import path from 'node:path';
import type { RequestHandler } from './$types';
import { DATA_DIRECTORY } from '$lib/server/application-paths';
import { managedDetector } from '$lib/server/detector-service';
import { readLogTail } from '$lib/server/detector-log';

export const GET: RequestHandler = async ({ request, url }) => {
	const detector = managedDetector();
	const text = detector
		? await detector.log.read()
		: await readLogTail(path.join(DATA_DIRECTORY, 'logs', 'detector.log'));
	const etag = `"${createHash('sha256').update(text).digest('hex')}"`;
	const headers = {
		'Content-Type': 'text/plain; charset=utf-8',
		'Cache-Control': 'private, no-cache',
		ETag: etag
	};
	if (url.searchParams.has('download')) {
		return new Response(text, {
			headers: { ...headers, 'Content-Disposition': 'attachment; filename="ai-detector.log"' }
		});
	}
	return request.headers.get('If-None-Match') === etag
		? new Response(null, { status: 304, headers })
		: new Response(text, { headers });
};

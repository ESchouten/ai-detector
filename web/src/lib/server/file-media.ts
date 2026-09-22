import { open } from 'node:fs/promises';
import { Readable } from 'node:stream';
import { isMissingFile } from './archive.ts';

/** Unsupported multipart ranges are served in full; an unsatisfiable range gets 416. */
function byteRange(
	header: string | null,
	size: number
): { start: number; end: number } | null | false {
	const match = header?.match(/^bytes=(\d*)-(\d*)$/);
	if (!match || (!match[1] && !match[2])) return null;
	const start = match[1] ? Number(match[1]) : Math.max(0, size - Number(match[2]));
	const end = match[1] && match[2] ? Math.min(Number(match[2]), size - 1) : size - 1;
	return start > end || start >= size ? false : { start, end };
}

export async function fileMedia(
	filename: string,
	request: Request,
	contentType: string
): Promise<Response> {
	let file;
	try {
		file = await open(filename);
	} catch (error) {
		if (isMissingFile(error)) return new Response('Not found', { status: 404 });
		throw error;
	}
	try {
		const stats = await file.stat();
		if (!stats.isFile()) {
			await file.close();
			return new Response('Not found', { status: 404 });
		}
		const range =
			request.method === 'HEAD' || request.headers.has('if-range')
				? null
				: byteRange(request.headers.get('range'), stats.size);
		if (range === false) {
			await file.close();
			return new Response(null, {
				status: 416,
				headers: { 'Content-Range': `bytes */${stats.size}` }
			});
		}
		const headers = new Headers({
			'Content-Type': contentType,
			'Content-Length': String(range ? range.end - range.start + 1 : stats.size),
			'Accept-Ranges': 'bytes',
			'Cache-Control': 'private, max-age=30',
			'X-Content-Type-Options': 'nosniff'
		});
		if (range) headers.set('Content-Range', `bytes ${range.start}-${range.end}/${stats.size}`);
		if (request.method === 'HEAD') {
			await file.close();
			return new Response(null, { headers });
		}
		// An already-aborted Node stream emits its error before toWeb can attach a listener.
		request.signal.throwIfAborted();
		const stream = file.createReadStream({ ...range, signal: request.signal });
		return new Response(Readable.toWeb(stream) as ReadableStream<Uint8Array>, {
			status: range ? 206 : 200,
			headers
		});
	} catch (error) {
		await file.close();
		throw error;
	}
}

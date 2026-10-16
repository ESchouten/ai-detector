import { open } from 'node:fs/promises';
import path from 'node:path';
import { Readable } from 'node:stream';
import { STAGES } from '../schema.ts';
import { archivePath, ArchivePathError } from './archive.ts';
import { isMissingFile } from './json-file.ts';

/** The pictures and clips a recording can hold, by extension. */
export const MEDIA_TYPES: Record<string, string> = {
	'.jpg': 'image/jpeg',
	'.jpeg': 'image/jpeg',
	'.png': 'image/png',
	'.gif': 'image/gif',
	'.webp': 'image/webp',
	'.bmp': 'image/bmp',
	'.mp4': 'video/mp4',
	'.webm': 'video/webm',
	'.mov': 'video/quicktime'
};
const ARCHIVE_TYPES: Record<string, string> = { ...MEDIA_TYPES, '.json': 'application/json' };

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
		if (isMissingFile(error)) return new Response(/* @wc-ignore */ 'Not found', { status: 404 });
		throw error;
	}
	try {
		const stats = await file.stat();
		if (!stats.isFile()) {
			await file.close();
			return new Response(/* @wc-ignore */ 'Not found', { status: 404 });
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

export async function archiveMedia(
	directory: string,
	location: { category: string; stage: string; timestamp: string; resource: string },
	request: Request
): Promise<Response> {
	const { category, stage, timestamp, resource } = location;
	const contentType = ARCHIVE_TYPES[path.extname(resource).toLowerCase()];
	if (!STAGES.some((value) => value === stage) || !contentType)
		return new Response(/* @wc-ignore */ 'Not found', { status: 404 });
	try {
		return await fileMedia(
			await archivePath(directory, category, stage, timestamp, resource),
			request,
			contentType
		);
	} catch (error) {
		if (error instanceof ArchivePathError || isMissingFile(error))
			return new Response(/* @wc-ignore */ 'Not found', { status: 404 });
		throw error;
	}
}

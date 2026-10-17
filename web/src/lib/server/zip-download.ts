import { once } from 'node:events';
import { createReadStream } from 'node:fs';
import { addAbortSignal, Readable } from 'node:stream';
import { ZipArchive } from 'archiver';

export type ZipEntry = { name: string } & ({ file: string } | { content: string });

async function appendEntries(
	zip: ZipArchive,
	entries: AsyncIterable<ZipEntry> | Iterable<ZipEntry>,
	signal: AbortSignal
): Promise<void> {
	for await (const entry of entries) {
		signal.throwIfAborted();
		const source = 'file' in entry ? createReadStream(entry.file, { signal }) : entry.content;
		if (typeof source !== 'string') source.on('error', (error) => zip.destroy(error));
		const appended = once(zip, 'entry', { signal });
		zip.append(source, { name: entry.name });
		await appended;
	}
	await zip.finalize();
}

/** Stream one file at a time; browser cancellation also closes the current source. */
export function zipDownload(
	filename: string,
	entries: AsyncIterable<ZipEntry> | Iterable<ZipEntry>,
	request: Request
): Response {
	request.signal.throwIfAborted();
	// Images and videos are already compressed. Storing them avoids competing with detection.
	const zip = new ZipArchive({ store: true, highWaterMark: 64 * 1024 });
	const lifetime = new AbortController();
	zip.once('close', () => {
		lifetime.abort();
		zip.abort();
	});
	zip.on('warning', (error) => zip.destroy(error));
	addAbortSignal(request.signal, zip);
	const body = Readable.toWeb(zip, {
		strategy: { highWaterMark: 64 * 1024, size: (chunk) => chunk.byteLength }
	}) as ReadableStream<Uint8Array>;
	void appendEntries(zip, entries, lifetime.signal).catch((error) => zip.destroy(error));
	return new Response(body, {
		headers: {
			'Content-Type': 'application/zip',
			'Content-Disposition': `attachment; filename="${filename}"`,
			'Cache-Control': 'no-store',
			'X-Content-Type-Options': 'nosniff'
		}
	});
}

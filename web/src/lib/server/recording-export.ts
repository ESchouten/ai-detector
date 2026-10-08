import { readdir } from 'node:fs/promises';
import path from 'node:path';
import type { RecordingExportFilter } from '../detections.ts';
import { archivePath, type ArchiveLocation, type DetectionArchive } from './archive.ts';
import { zipDownload, type ZipEntry } from './zip-download.ts';

const MEDIA_EXTENSIONS = new Set([
	'.jpg',
	'.jpeg',
	'.png',
	'.gif',
	'.webp',
	'.bmp',
	'.mp4',
	'.webm',
	'.mov'
]);

const PHOTO_FILES = new Set(['clean.jpg', 'metadata.json']);

function photosNotice(): string {
	return 'This export holds the original photos only: pictures with boxes and video clips were left out.\n';
}

async function* recordingFiles(
	directory: string,
	locations: ArchiveLocation[],
	photosOnly: boolean
): AsyncGenerator<ZipEntry> {
	if (photosOnly) yield { name: 'PHOTOS-ONLY.txt', content: photosNotice() };
	yield {
		name: 'README.txt',
		content: `AI Detector recordings

${locations.length} recorded events.

Files are grouped by category, stage and recording timestamp under detections/.
clean.jpg is the original image when available; best.jpg includes annotations.
Other saved images, video clips and metadata.json are included unchanged.
Manual reviews override the original stage. In metadata.json, review records the
manual decision and its origin; validated remains the validator's original result.
Dates follow the recording dates shown in AI Detector.

An accepted event is not a verified bounding-box annotation. Review and annotate
the original images or video frames before using them to train a model.

This export does not include application settings or camera login details.
`
	};
	const names = new Map<string, number>();
	for (const { type, stage, timestamp } of locations) {
		const name = path.posix.join(type, stage, timestamp);
		names.set(name, (names.get(name) ?? 0) + 1);
	}
	for (const { type, stage, archiveStage, timestamp } of locations) {
		const folder = await archivePath(directory, type, archiveStage, timestamp);
		// Older archives can have the same timestamp in different stages. Reviewing must not overwrite either in the ZIP.
		const uniqueTimestamp =
			names.get(path.posix.join(type, stage, timestamp))! > 1
				? `${timestamp}-${archiveStage}`
				: timestamp;
		const target = path.posix.join('detections', type, stage, uniqueTimestamp);
		const entries = await readdir(folder, { withFileTypes: true });
		for (const entry of entries) {
			if (!entry.isFile() || (photosOnly && !PHOTO_FILES.has(entry.name))) continue;
			if (
				entry.name !== 'metadata.json' &&
				!MEDIA_EXTENSIONS.has(path.extname(entry.name).toLowerCase())
			)
				continue;
			yield {
				name: path.posix.join(target, entry.name),
				file: await archivePath(directory, type, archiveStage, timestamp, entry.name)
			};
		}
	}
}

export async function exportRecordings(
	archive: DetectionArchive,
	filter: RecordingExportFilter,
	request: Request
): Promise<Response> {
	const { content, ...selection } = filter;
	const locations = await archive.locations(selection);
	if (!locations.length) return new Response('No recordings match these filters.', { status: 404 });
	return zipDownload(
		`AI-Detector-recordings-${new Date().toISOString().slice(0, 10)}.zip`,
		recordingFiles(archive.directory, locations, content === 'photos'),
		request
	);
}

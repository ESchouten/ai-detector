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

async function* recordingFiles(
	directory: string,
	locations: ArchiveLocation[]
): AsyncGenerator<ZipEntry> {
	yield {
		name: 'README.txt',
		content: `AI Detector recordings

${locations.length} recorded events.

Files are grouped by category, stage and recording timestamp under detections/.
clean.jpg is the original image when available; best.jpg includes annotations.
Other saved images, video clips and metadata.json are included unchanged.
Dates follow the recording dates shown in AI Detector.

These are model predictions, not reviewed training labels. Review and annotate
the original images or video frames before using them to train a model.

This export does not include application settings or camera login details.
`
	};
	for (const { type, stage, timestamp } of locations) {
		const folder = await archivePath(directory, type, stage, timestamp);
		const entries = await readdir(folder, { withFileTypes: true });
		for (const entry of entries) {
			if (!entry.isFile()) continue;
			if (
				entry.name !== 'metadata.json' &&
				!MEDIA_EXTENSIONS.has(path.extname(entry.name).toLowerCase())
			)
				continue;
			yield {
				name: path.posix.join('detections', type, stage, timestamp, entry.name),
				file: await archivePath(directory, type, stage, timestamp, entry.name)
			};
		}
	}
}

export async function exportRecordings(
	archive: DetectionArchive,
	filter: RecordingExportFilter,
	request: Request
): Promise<Response> {
	const locations = await archive.locations(filter);
	if (!locations.length) return new Response('No recordings match these filters.', { status: 404 });
	return zipDownload(
		`AI-Detector-recordings-${new Date().toISOString().slice(0, 10)}.zip`,
		recordingFiles(archive.directory, locations),
		request
	);
}

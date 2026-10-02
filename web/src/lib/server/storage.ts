import { createHash } from 'node:crypto';
import { mkdir, readdir, rm, statfs } from 'node:fs/promises';
import path from 'node:path';
import type { Config } from '../schema.ts';
import { archivePath, type DetectionArchive } from './archive.ts';

export async function diskSpace(directory: string) {
	await mkdir(directory, { recursive: true });
	const { bsize, bavail, blocks } = await statfs(directory);
	const available = bsize * bavail;
	const total = bsize * blocks;
	return { available, total, low: available < Math.max(2 * 1024 ** 3, total * 0.05) };
}

export async function recordingCleanup(archive: DetectionArchive, before: string) {
	const locations = (await archive.addresses()).filter(
		(item) => item.timestamp.slice(0, 10) < before
	);
	const revision = createHash('sha256')
		.update(
			JSON.stringify(
				locations.map(({ type, archiveStage, timestamp }) => [type, archiveStage, timestamp])
			)
		)
		.digest('hex');
	return { locations, revision, count: locations.length };
}

/** Only remove the completed events the user just reviewed; active .pending events are excluded. */
export async function removeRecordings(
	archive: DetectionArchive,
	before: string,
	revision: string
): Promise<number> {
	const preview = await recordingCleanup(archive, before);
	if (preview.revision !== revision)
		throw new Error('The recordings changed. Check the number of recordings and confirm again.');
	let removed = 0;
	try {
		for (const location of preview.locations) {
			const folder = await archivePath(
				archive.directory,
				location.type,
				location.archiveStage,
				location.timestamp
			);
			await rm(folder, { recursive: true });
			removed++;
		}
	} finally {
		archive.invalidate();
	}
	return removed;
}

/** Called only while monitoring is paused. Originals referenced by settings are preserved. */
export async function clearModelCache(directory: string, config: Config): Promise<void> {
	const models = path.join(directory, 'models');
	const retained = new Set(
		config.detectors.flatMap((detector) => {
			const model = detector.yolo?.model;
			if (!model) return [];
			const relative = path.relative(models, path.resolve(directory, model));
			return [
				createHash('sha256').update(model).digest('hex').slice(0, 16),
				path.basename(model),
				relative.split(path.sep)[0]
			];
		})
	);
	let entries;
	try {
		entries = await readdir(models, { withFileTypes: true });
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === 'ENOENT') return;
		throw error;
	}
	for (const entry of entries) {
		if (entry.isSymbolicLink() || retained.has(entry.name)) continue;
		if (entry.isDirectory() && (entry.name === 'prepared' || /^[a-f0-9]{16}$/.test(entry.name)))
			await rm(path.join(models, entry.name), { recursive: true });
	}
}

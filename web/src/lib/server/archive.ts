import { readdir, readFile, realpath } from 'node:fs/promises';
import path from 'node:path';
import Ajv from 'ajv';
import metadataSchema from '../../../../config/metadata.schema.json' with { type: 'json' };
import { STAGES, type Metadata, type Stage } from '../schema.ts';
import type { Detection, DetectionFilter, DetectionPage } from '../detections.ts';
import { isArchiveSegment, type RecordingExportFilter } from '../detections.ts';

export { isArchiveSegment } from '../detections.ts';

export class ArchivePathError extends Error {}

const validateMetadata = new Ajv().compile<Metadata>(metadataSchema);

export function isMissingFile(error: unknown): boolean {
	return ['ENOENT', 'ENOTDIR'].includes((error as NodeJS.ErrnoException).code ?? '');
}

/** Keep decoded URL segments and symbolic links inside the recording directory. */
export async function archivePath(root: string, ...segments: string[]): Promise<string> {
	if (!segments.every(isArchiveSegment)) throw new ArchivePathError('Invalid archive path.');
	const [directory, file] = await Promise.all([
		realpath(root),
		realpath(path.join(root, ...segments))
	]);
	const relative = path.relative(directory, file);
	if (relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) {
		throw new ArchivePathError('Invalid archive path.');
	}
	return file;
}

async function folders(directory: string): Promise<string[]> {
	try {
		const entries = await readdir(directory, { withFileTypes: true });
		return entries
			.filter((entry) => entry.isDirectory())
			.map((entry) => entry.name)
			.sort();
	} catch (error) {
		if (isMissingFile(error)) return [];
		throw error;
	}
}

export interface ArchiveLocation {
	type: string;
	stage: Stage;
	timestamp: string;
}

export class DetectionArchive {
	readonly directory: string;

	constructor(directory: string) {
		this.directory = directory;
	}

	types(): Promise<string[]> {
		return folders(this.directory);
	}

	async page({ type, stage, offset, limit }: DetectionFilter): Promise<DetectionPage> {
		const locations = await this.locations({ type, stage });
		const page = locations.slice(offset, offset + limit);
		const items = await Promise.all(page.map((location) => this.read(location)));
		return {
			items,
			nextOffset: offset + items.length,
			hasMore: offset + items.length < locations.length
		};
	}

	async locations({ type, stage, from, to }: RecordingExportFilter): Promise<ArchiveLocation[]> {
		if (type !== undefined && !isArchiveSegment(type))
			throw new ArchivePathError('Invalid category.');
		const types = type ? [type] : await this.types();
		const locations: ArchiveLocation[] = [];
		for (const category of types) {
			for (const currentStage of stage ? [stage] : STAGES) {
				const timestamps = await folders(path.join(this.directory, category, currentStage));
				for (const timestamp of timestamps) {
					// Match the calendar dates shown in Recordings, without timezone conversion.
					const day = timestamp.slice(0, 10);
					if ((!from || day >= from) && (!to || day <= to))
						locations.push({ type: category, stage: currentStage, timestamp });
				}
			}
		}
		// The detector's fixed-width ISO directory names sort chronologically.
		locations.sort(
			(a, b) =>
				b.timestamp.localeCompare(a.timestamp) ||
				a.type.localeCompare(b.type) ||
				a.stage.localeCompare(b.stage)
		);
		return locations;
	}

	private async read(location: ArchiveLocation): Promise<Detection> {
		const file = await archivePath(
			this.directory,
			location.type,
			location.stage,
			location.timestamp,
			'metadata.json'
		);
		const metadata: unknown = JSON.parse(await readFile(file, 'utf8'));
		if (!validateMetadata(metadata))
			throw new Error(
				`Invalid archive metadata: ${location.type}/${location.stage}/${location.timestamp}`
			);
		return { ...metadata, ...location };
	}
}

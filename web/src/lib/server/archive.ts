import { readdir, readFile, realpath, unlink } from 'node:fs/promises';
import path from 'node:path';
import Ajv from 'ajv';
import * as v from 'valibot';
import metadataSchema from '../../../../config/metadata.schema.json' with { type: 'json' };
import { STAGES, type Metadata, type Stage } from '../schema.ts';
import type { Detection, DetectionFilter, DetectionPage } from '../detections.ts';
import {
	isArchiveSegment,
	manualReviewSchema,
	reviewedStage,
	type ManualReview,
	type RecordingExportFilter
} from '../detections.ts';
import { writeJson } from './json-file.ts';

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
	archiveStage: Stage;
	timestamp: string;
	review: ManualReview | null;
}

export type RecordingAddress = Pick<ArchiveLocation, 'type' | 'archiveStage' | 'timestamp'>;

export class DetectionArchive {
	readonly directory: string;
	private pendingReview: Promise<unknown> = Promise.resolve();

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
			for (const currentStage of STAGES) {
				const timestamps = await folders(path.join(this.directory, category, currentStage));
				for (const timestamp of timestamps) {
					// Match the calendar dates shown in Recordings, without timezone conversion.
					const day = timestamp.slice(0, 10);
					if ((from && day < from) || (to && day > to)) continue;
					const address = { type: category, archiveStage: currentStage, timestamp };
					const review = await this.readReview(address);
					const effectiveStage = reviewedStage(currentStage, review);
					if (!stage || stage === effectiveStage)
						locations.push({ ...address, stage: effectiveStage, review });
				}
			}
		}
		// The detector's fixed-width ISO directory names sort chronologically.
		locations.sort(
			(a, b) =>
				b.timestamp.localeCompare(a.timestamp) ||
				a.type.localeCompare(b.type) ||
				a.archiveStage.localeCompare(b.archiveStage)
		);
		return locations;
	}

	private async read(location: ArchiveLocation): Promise<Detection> {
		const file = await archivePath(
			this.directory,
			location.type,
			location.archiveStage,
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

	async readReview(address: RecordingAddress): Promise<ManualReview | null> {
		try {
			const file = await archivePath(
				this.directory,
				address.type,
				address.archiveStage,
				address.timestamp,
				'review.json'
			);
			return v.parse(manualReviewSchema, JSON.parse(await readFile(file, 'utf8')));
		} catch (error) {
			if (isMissingFile(error)) return null;
			throw error;
		}
	}

	review(
		address: RecordingAddress,
		validated: boolean | null,
		source: ManualReview['source']
	): Promise<Detection> {
		return this.enqueueReview(async () => {
			const current = await this.read({
				...address,
				stage: address.archiveStage,
				review: await this.readReview(address)
			});
			// All disk destinations for a new event share its ID. Legacy recordings remain reviewable by location.
			const locations = current.event_id ? await this.findEvent(current.event_id) : [current];
			await this.writeReviews(locations, validated, source);
			const review = await this.readReview(address);
			return {
				...current,
				review,
				stage: reviewedStage(address.archiveStage, review)
			};
		});
	}

	reviewEvent(id: string, validated: boolean, source: ManualReview['source']): Promise<boolean> {
		return this.enqueueReview(async () => {
			const locations = await this.findEvent(id);
			await this.writeReviews(locations, validated, source);
			return locations.length > 0;
		});
	}

	private enqueueReview<T>(operation: () => Promise<T>): Promise<T> {
		const result = this.pendingReview.then(operation);
		this.pendingReview = result.catch(() => undefined);
		return result;
	}

	private async findEvent(id: string): Promise<Detection[]> {
		const matches: Detection[] = [];
		for (const location of await this.locations({})) {
			const recording = await this.read(location);
			if (recording.event_id === id) matches.push(recording);
		}
		return matches;
	}

	private async writeReviews(
		locations: ArchiveLocation[],
		validated: boolean | null,
		source: ManualReview['source']
	): Promise<void> {
		const review: ManualReview | null =
			validated === null ? null : { validated, source, reviewed_at: new Date().toISOString() };
		for (const address of locations) {
			const folder = await archivePath(
				this.directory,
				address.type,
				address.archiveStage,
				address.timestamp
			);
			// Validate any existing sidecar, including symlinks, before replacing it.
			await this.readReview(address);
			const file = path.join(folder, 'review.json');
			if (review) await writeJson(file, review);
			else
				await unlink(file).catch((error: unknown) => {
					if (!isMissingFile(error)) throw error;
				});
		}
	}
}

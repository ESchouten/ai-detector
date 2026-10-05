import { readdir, readFile, realpath, stat, unlink } from 'node:fs/promises';
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
import { webLog } from './web-log.ts';

export { isArchiveSegment } from '../detections.ts';

export class ArchivePathError extends Error {}
class ArchiveDataError extends Error {}

const validateMetadata = new Ajv().compile<Metadata>(metadataSchema);

export function isMissingFile(error: unknown): boolean {
	return ['ENOENT', 'ENOTDIR'].includes((error as NodeJS.ErrnoException).code ?? '');
}

/** Keep decoded URL segments and symbolic links inside the recording directory. */
export async function archivePath(root: string, ...segments: string[]): Promise<string> {
	if (!segments.every(isArchiveSegment))
		throw new ArchivePathError(/* @wc-ignore */ 'Invalid archive path.');
	const [directory, file] = await Promise.all([
		realpath(root),
		realpath(path.join(root, ...segments))
	]);
	const relative = path.relative(directory, file);
	if (relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) {
		throw new ArchivePathError(/* @wc-ignore */ 'Invalid archive path.');
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
	private directories = new Map<string, { modified: number; names: string[] }>();
	private reviews = new Map<string, { checked: number; review: ManualReview | null }>();
	private eventIds = new Map<string, string | undefined>();
	private warnings = new Map<string, string>();

	constructor(directory: string) {
		this.directory = directory;
	}

	types(): Promise<string[]> {
		return this.folders(this.directory);
	}

	private async folders(directory: string): Promise<string[]> {
		try {
			const { mtimeMs } = await stat(directory);
			const cached = this.directories.get(directory);
			if (cached?.modified === mtimeMs) return cached.names;
			const names = await folders(directory);
			this.directories.set(directory, { modified: mtimeMs, names });
			return names;
		} catch (error) {
			if (isMissingFile(error)) {
				this.directories.delete(directory);
				return [];
			}
			throw error;
		}
	}

	invalidate(): void {
		this.directories.clear();
		this.reviews.clear();
		this.eventIds.clear();
		this.warnings.clear();
	}

	private unavailable(address: RecordingAddress, error: unknown, kind = 'metadata'): void {
		if (
			!(
				error instanceof SyntaxError ||
				error instanceof ArchiveDataError ||
				error instanceof v.ValiError ||
				isMissingFile(error)
			)
		)
			throw error;
		const key = `${kind}:${this.addressKey(address)}`;
		const message = `Could not read recording ${address.type}/${address.archiveStage}/${address.timestamp}. Other recordings remain available.`;
		if (!this.warnings.has(key)) webLog.warn(message, error);
		this.warnings.set(key, message);
	}

	async page({ type, stage, offset, limit }: DetectionFilter): Promise<DetectionPage> {
		const locations = await this.locations({ type, stage });
		const items: Detection[] = [];
		let nextOffset = offset;
		while (items.length < limit && nextOffset < locations.length) {
			const location = locations[nextOffset++];
			try {
				items.push(await this.read(location));
			} catch (error) {
				this.unavailable(location, error);
			}
		}
		return {
			items,
			nextOffset,
			hasMore: nextOffset < locations.length,
			warnings: Array.from(this.warnings.values())
		};
	}

	/** Completed archive folders, independent of optional review or metadata files. */
	async addresses({ type, from, to }: Omit<RecordingExportFilter, 'stage'> = {}): Promise<
		RecordingAddress[]
	> {
		if (type !== undefined && !isArchiveSegment(type))
			throw new ArchivePathError('Invalid category.');
		const types = type ? [type] : await this.types();
		const locations: RecordingAddress[] = [];
		for (const category of types) {
			for (const currentStage of STAGES) {
				const timestamps = await this.folders(path.join(this.directory, category, currentStage));
				for (const timestamp of timestamps) {
					// Match the calendar dates shown in Recordings, without timezone conversion.
					const day = timestamp.slice(0, 10);
					if ((from && day < from) || (to && day > to)) continue;
					locations.push({ type: category, archiveStage: currentStage, timestamp });
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

	async locations({ stage, ...filter }: RecordingExportFilter): Promise<ArchiveLocation[]> {
		const locations: ArchiveLocation[] = [];
		for (const address of await this.addresses(filter)) {
			let review: ManualReview | null;
			try {
				review = await this.cachedReview(address);
			} catch (error) {
				this.unavailable(address, error, 'review');
				continue;
			}
			const effectiveStage = reviewedStage(address.archiveStage, review);
			if (!stage || stage === effectiveStage)
				locations.push({ ...address, stage: effectiveStage, review });
		}
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
			throw new ArchiveDataError(
				/* @wc-ignore */ `Invalid archive metadata: ${location.type}/${location.stage}/${location.timestamp}`
			);
		this.eventIds.set(this.addressKey(location), metadata.event_id ?? undefined);
		this.warnings.delete(`metadata:${this.addressKey(location)}`);
		return { ...metadata, ...location };
	}

	private addressKey(address: RecordingAddress): string {
		return JSON.stringify([address.type, address.archiveStage, address.timestamp]);
	}

	private cachedReview(address: RecordingAddress): Promise<ManualReview | null> {
		const cached = this.reviews.get(this.addressKey(address));
		return cached && Date.now() - cached.checked < 30000
			? Promise.resolve(cached.review)
			: this.readReview(address);
	}

	async readReview(address: RecordingAddress): Promise<ManualReview | null> {
		let review: ManualReview | null;
		try {
			const file = await archivePath(
				this.directory,
				address.type,
				address.archiveStage,
				address.timestamp,
				'review.json'
			);
			review = v.parse(manualReviewSchema, JSON.parse(await readFile(file, 'utf8')));
		} catch (error) {
			if (!isMissingFile(error)) throw error;
			review = null;
		}
		this.reviews.set(this.addressKey(address), { checked: Date.now(), review });
		this.warnings.delete(`review:${this.addressKey(address)}`);
		return review;
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
			const key = this.addressKey(location);
			if (this.eventIds.has(key) && this.eventIds.get(key) !== id) continue;
			try {
				const recording = await this.read(location);
				if (recording.event_id === id) matches.push(recording);
			} catch (error) {
				this.unavailable(location, error);
			}
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
			this.reviews.set(this.addressKey(address), { checked: Date.now(), review });
		}
	}
}

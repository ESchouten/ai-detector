import { readdir, readFile, realpath, rm, stat } from 'node:fs/promises';
import path from 'node:path';
import Ajv from 'ajv';
import * as v from 'valibot';
import writeFileAtomic from 'write-file-atomic';
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
import { serialQueue } from './serial.ts';
import { webLog } from './web-log.ts';

export { isArchiveSegment } from '../detections.ts';

export class ArchivePathError extends Error {}
class ArchiveDataError extends Error {}

const validateMetadata = new Ajv().compile<Metadata>(metadataSchema);
const savedReview = v.nullish(manualReviewSchema);
/** Where a review lived before it became part of metadata.json. */
const REVIEW_READS = 32;

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
	private readonly enqueueReview = serialQueue();
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

	private unavailable(address: RecordingAddress, error: unknown): void {
		if (
			!(
				error instanceof SyntaxError ||
				error instanceof ArchiveDataError ||
				error instanceof v.ValiError ||
				isMissingFile(error)
			)
		)
			throw error;
		const key = this.addressKey(address);
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

	/** Completed archive folders, whether or not their metadata can be read. */
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
		const addresses = await this.addresses(filter);
		const locations: ArchiveLocation[] = [];
		// Each review is read from its recording's metadata; several at once keeps a large archive quick.
		for (let start = 0; start < addresses.length; start += REVIEW_READS) {
			const batch = addresses.slice(start, start + REVIEW_READS);
			const reviews = await Promise.all(
				batch.map((address) =>
					this.cachedReview(address).catch((error) => {
						this.unavailable(address, error);
						return undefined;
					})
				)
			);
			for (const [index, address] of batch.entries()) {
				const review = reviews[index];
				if (review === undefined) continue;
				const effectiveStage = reviewedStage(address.archiveStage, review);
				if (!stage || stage === effectiveStage)
					locations.push({ ...address, stage: effectiveStage, review });
			}
		}
		return locations;
	}

	/** The recordings that began between two moments, newest first. */
	async between(from: Date, to: Date): Promise<Detection[]> {
		const day = (moment: Date) => new Date(moment.getTime() - moment.getTimezoneOffset() * 60000);
		const locations = await this.locations({
			from: day(from).toISOString().slice(0, 10),
			to: day(to).toISOString().slice(0, 10)
		});
		const items: Detection[] = [];
		for (let start = 0; start < locations.length; start += REVIEW_READS) {
			const batch = await Promise.all(
				locations.slice(start, start + REVIEW_READS).map((location) =>
					this.read(location).catch((error) => {
						this.unavailable(location, error);
						return undefined;
					})
				)
			);
			for (const item of batch) {
				const began = item ? Date.parse(item.start) : NaN;
				if (item && began >= from.getTime() && began <= to.getTime()) items.push(item);
			}
		}
		return items;
	}

	private async read(location: ArchiveLocation): Promise<Detection> {
		const { metadata } = await this.metadataFile(location);
		if (!validateMetadata(metadata))
			throw new ArchiveDataError(
				/* @wc-ignore */ `Invalid archive metadata: ${location.type}/${location.stage}/${location.timestamp}`
			);
		this.eventIds.set(this.addressKey(location), metadata.event_id ?? undefined);
		this.warnings.delete(this.addressKey(location));
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

	/**
	 * The review a person gave this recording, kept as `review` in its metadata.json beside
	 * the validator's own result. A recording whose metadata cannot be read at all has none:
	 * it stays listed in its original stage, and reading it reports the damage. A review
	 * that is present but not understood is an error, so the decision is never ignored.
	 */
	async readReview(address: RecordingAddress): Promise<ManualReview | null> {
		let review: ManualReview | null = null;
		try {
			const { metadata } = await this.readMetadata(address);
			review = v.parse(savedReview, metadata.review) ?? null;
		} catch (error) {
			if (
				!(isMissingFile(error) || error instanceof SyntaxError || error instanceof ArchiveDataError)
			)
				throw error;
		}
		this.reviews.set(this.addressKey(address), { checked: Date.now(), review });
		return review;
	}

	/** A recording's metadata.json as parsed, and its real location inside the archive. */
	private async metadataFile(
		address: RecordingAddress
	): Promise<{ file: string; metadata: unknown }> {
		const file = await archivePath(
			this.directory,
			address.type,
			address.archiveStage,
			address.timestamp,
			'metadata.json'
		);
		return { file, metadata: JSON.parse(await readFile(file, 'utf8')) };
	}

	/** The metadata as saved, with every field kept, for reading or replacing only its review. */
	private async readMetadata(
		address: RecordingAddress
	): Promise<{ file: string; metadata: Record<string, unknown> }> {
		const { file, metadata } = await this.metadataFile(address);
		if (typeof metadata !== 'object' || metadata === null || Array.isArray(metadata))
			throw new ArchiveDataError(/* @wc-ignore */ 'Archive metadata is not an object.');
		return { file, metadata: metadata as Record<string, unknown> };
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
			// All disk destinations of an event share its ID. A recording without one is reviewed by location.
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

	/** Remove one recording with its pictures and clip. A copy in another category stays. */
	remove({ type, archiveStage, timestamp }: RecordingAddress): Promise<void> {
		return this.enqueueReview(async () => {
			try {
				await rm(await archivePath(this.directory, type, archiveStage, timestamp), {
					recursive: true
				});
			} finally {
				this.invalidate();
			}
		});
	}

	reviewEvent(id: string, validated: boolean, source: ManualReview['source']): Promise<boolean> {
		return this.enqueueReview(async () => {
			const locations = await this.findEvent(id);
			await this.writeReviews(locations, validated, source);
			return locations.length > 0;
		});
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
		locations: RecordingAddress[],
		validated: boolean | null,
		source: ManualReview['source']
	): Promise<void> {
		const review: ManualReview | null =
			validated === null ? null : { validated, source, reviewed_at: new Date().toISOString() };
		for (const address of locations) await this.saveReview(address, review);
	}

	/**
	 * Replace only the review in a recording's metadata.json. The detector publishes that file
	 * once and never rewrites it, so everything else in it, including the validator's own
	 * verdict, keeps its value.
	 */
	private async saveReview(address: RecordingAddress, review: ManualReview | null): Promise<void> {
		const { file, metadata } = await this.readMetadata(address);
		// Refuse to replace a review that cannot be understood.
		v.parse(savedReview, metadata.review);
		if (review) metadata.review = review;
		else delete metadata.review;
		// No mode is given, so the file keeps the permissions the detector gave it.
		await writeFileAtomic(file, JSON.stringify(metadata));
		this.reviews.set(this.addressKey(address), { checked: Date.now(), review });
	}
}

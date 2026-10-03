import { randomUUID } from 'node:crypto';
import { readdir, rm } from 'node:fs/promises';
import path from 'node:path';
import * as v from 'valibot';
import { readJson, writeJson } from './json-file.ts';

const id = v.pipe(v.string(), v.regex(/^[a-f0-9]{32}$/));
const name = v.pipe(v.string(), v.trim(), v.minLength(1), v.maxLength(80));
const cowSchema = v.strictObject({
	id,
	name,
	samples: v.pipe(v.array(id), v.maxLength(32))
});
const catalogSchema = v.strictObject({
	version: v.literal(1),
	revision: v.pipe(v.number(), v.integer(), v.minValue(0)),
	identities: v.pipe(v.array(cowSchema), v.maxLength(500))
});
const sightingSchema = v.strictObject({
	version: v.literal(1),
	id,
	image: id,
	source: v.pipe(v.string(), v.regex(/^[a-f0-9]{64}$/)),
	captured_at: v.pipe(
		v.string(),
		v.check((value) => Number.isFinite(Date.parse(value)))
	),
	track_id: v.nullable(v.pipe(v.number(), v.integer())),
	gallery_revision: v.optional(v.nullable(v.pipe(v.number(), v.integer(), v.minValue(0)))),
	identity: v.strictObject({
		id: v.nullable(id),
		name: v.nullable(v.string()),
		similarity: v.nullable(v.pipe(v.number(), v.minValue(-1), v.maxValue(1)))
	})
});
type Catalog = v.InferOutput<typeof catalogSchema>;
type Sighting = v.InferOutput<typeof sightingSchema>;

export class HerdError extends Error {
	readonly status: 400 | 409;
	constructor(message: string, status: 400 | 409 = 400) {
		super(message);
		this.status = status;
	}
}

function parseCatalog(value: unknown): Catalog {
	const parsed = v.safeParse(catalogSchema, value);
	if (!parsed.success)
		throw new HerdError('The herd file is invalid. Restore a valid catalog.json.');
	const catalog = parsed.output;
	const ids = catalog.identities.map((cow) => cow.id);
	const names = catalog.identities.map((cow) => cow.name.toLowerCase());
	const samples = catalog.identities.flatMap((cow) => cow.samples);
	if ([ids, names, samples].some((values) => new Set(values).size !== values.length))
		throw new HerdError('Each cow name and confirmed photo must be unique.');
	return catalog;
}

function findCow(catalog: Catalog, cowId: string) {
	const cow = catalog.identities.find((item) => item.id === cowId);
	if (!cow) throw new HerdError('This cow was removed. Refresh the herd and try again.');
	return cow;
}

function cowName(value: string): string {
	const result = v.safeParse(name, value);
	if (!result.success) throw new HerdError('Enter a cow name or tag number, up to 80 characters.');
	return result.output;
}

export class IdentityCatalog {
	readonly directory: string;
	private pending: Promise<unknown> = Promise.resolve();

	constructor(dataDirectory: string) {
		this.directory = path.join(dataDirectory, 'identities');
	}

	private async read(): Promise<Catalog> {
		return parseCatalog(
			await readJson(path.join(this.directory, 'catalog.json'), {
				version: 1,
				revision: 0,
				identities: []
			})
		);
	}

	private async sighting(sightingId: string): Promise<Sighting | null> {
		if (!v.is(id, sightingId)) return null;
		let value: unknown;
		try {
			value = await readJson(path.join(this.directory, 'sightings', `${sightingId}.json`));
		} catch (error) {
			if (error instanceof SyntaxError) return null;
			throw error;
		}
		const result = v.safeParse(sightingSchema, value);
		return result.success && result.output.id === sightingId && result.output.image === sightingId
			? result.output
			: null;
	}

	async list() {
		await this.pending;
		const catalog = await this.read();
		let files: string[];
		try {
			files = await readdir(path.join(this.directory, 'sightings'));
		} catch (error) {
			if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
			files = [];
		}
		const samples = new Set(catalog.identities.flatMap((cow) => cow.samples));
		const pendingFiles = files.filter(
			(file) => /^[a-f0-9]{32}\.json$/.test(file) && !samples.has(file.slice(0, -5))
		);
		const sightings = await Promise.all(
			pendingFiles.map((file) => this.sighting(file.slice(0, -5)))
		);
		const review = sightings
			.filter((item): item is Sighting => item !== null)
			.map((item) =>
				item.gallery_revision === catalog.revision
					? item
					: { ...item, identity: { ...item.identity, id: null, name: null } }
			)
			.sort((a, b) => b.captured_at.localeCompare(a.captured_at));
		return {
			...catalog,
			identities: catalog.identities.sort((a, b) => a.name.localeCompare(b.name)),
			review,
			unavailable: sightings.filter((item) => item === null).length
		};
	}

	private change(revision: number, operation: (catalog: Catalog) => Promise<void> | void) {
		const result = this.pending.then(async () => {
			const catalog = await this.read();
			if (catalog.revision !== revision)
				throw new HerdError('The herd changed on another screen. Refresh and try again.', 409);
			await operation(catalog);
			catalog.revision++;
			await writeJson(path.join(this.directory, 'catalog.json'), parseCatalog(catalog));
		});
		this.pending = result.catch(() => undefined);
		return result;
	}

	assign(revision: number, sightingId: string, cowId: string | null, label: string) {
		return this.change(revision, async (catalog) => {
			const sighting = await this.sighting(sightingId);
			if (!sighting)
				throw new HerdError('This photo is no longer available. Refresh and try again.');
			if (catalog.identities.some((cow) => cow.samples.includes(sightingId)))
				throw new HerdError('This photo has already been confirmed.');
			const cow = cowId
				? findCow(catalog, cowId)
				: { id: randomUUID().replaceAll('-', ''), name: cowName(label), samples: [] as string[] };
			if (!cowId && catalog.identities.length >= 500)
				throw new HerdError('This herd already has 500 cows. Remove an unused cow first.');
			if (!cowId) catalog.identities.push(cow);
			if (cow.samples.length >= 32)
				throw new HerdError('This cow already has 32 examples. Remove a less useful photo first.');
			cow.samples.push(sightingId);
		});
	}

	rename(revision: number, cowId: string, label: string) {
		return this.change(revision, (catalog) => {
			findCow(catalog, cowId).name = cowName(label);
		});
	}

	removeExample(revision: number, cowId: string, sightingId: string) {
		return this.change(revision, (catalog) => {
			const cow = findCow(catalog, cowId);
			if (!cow.samples.includes(sightingId))
				throw new HerdError('This example was already removed.');
			cow.samples = cow.samples.filter((sample) => sample !== sightingId);
		});
	}

	removeCow(revision: number, cowId: string) {
		return this.change(revision, (catalog) => {
			findCow(catalog, cowId);
			catalog.identities = catalog.identities.filter((cow) => cow.id !== cowId);
		});
	}

	discard(revision: number, sightingId: string) {
		return this.change(revision, async (catalog) => {
			if (!v.is(id, sightingId)) throw new HerdError('Choose a valid photo.');
			if (catalog.identities.some((cow) => cow.samples.includes(sightingId)))
				throw new HerdError('Remove this confirmed example from its cow before discarding it.');
			const sighting = await this.sighting(sightingId);
			await rm(path.join(this.directory, 'sightings', `${sightingId}.json`), { force: true });
			if (sighting) await rm(this.image(sighting.image)!, { force: true });
		});
	}

	image(imageId: string): string | null {
		return v.is(id, imageId) ? path.join(this.directory, 'images', `${imageId}.jpg`) : null;
	}
}

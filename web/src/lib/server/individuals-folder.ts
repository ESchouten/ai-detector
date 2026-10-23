import { readdir } from 'node:fs/promises';
import path from 'node:path';
import type {
	IndividualsOverview,
	NamedIndividual,
	Sighting,
	SightingGroup
} from '../individuals.ts';
import { isMissingFile, readJson, writeJson } from './json-file.ts';

/** How many groups the page lists, and pictures per group or name. */
const GROUPS_SHOWN = 24;
const PICTURES_SHOWN = 12;
const SIGHTING_ID = /^[a-f0-9]{32}$/;
const PICTURE = /^crop-[1-9]\d*\.jpg$/;

interface NamesFile {
	version: 1;
	names: Record<string, string>;
}

interface GroupsFile {
	version: 1;
	model: string;
	groups: { sightings: string[]; suggestions: { name: string; score: number }[] }[];
}

export class SightingMissingError extends Error {}

/**
 * The detector's individuals folder (see the detector's architecture). The detector writes
 * sightings and groups.json; this service writes only names.json, whole, one change at a time.
 */
export class IndividualsFolder {
	readonly directory: string;
	#changes: Promise<unknown> = Promise.resolve();

	constructor(directory: string) {
		this.directory = directory;
	}

	get #names(): string {
		return path.join(this.directory, 'names.json');
	}

	#sighting(id: string): string {
		return path.join(this.directory, 'sightings', id);
	}

	async #readNames(): Promise<Record<string, string>> {
		return (await readJson<NamesFile>(this.#names))?.names ?? {};
	}

	async #record(id: string): Promise<Sighting | null> {
		const record = await readJson<Sighting>(path.join(this.#sighting(id), 'sighting.json'));
		return record && { id, seen: record.seen, crops: record.crops };
	}

	async #records(ids: string[]): Promise<Sighting[]> {
		return (await Promise.all(ids.map((id) => this.#record(id)))).filter((item) => !!item);
	}

	async #sightingIds(): Promise<string[]> {
		try {
			return (await readdir(path.join(this.directory, 'sightings'))).filter((name) =>
				SIGHTING_ID.test(name)
			);
		} catch (error) {
			if (isMissingFile(error)) return [];
			throw error;
		}
	}

	/** Look-alike unnamed sightings first, then any the detector has not grouped, newest first. */
	async #groups(unnamed: Set<string>) {
		const file = await readJson<GroupsFile>(path.join(this.directory, 'groups.json'));
		const grouped = (file?.groups ?? [])
			.map((group) => ({
				ids: group.sightings.filter((id) => unnamed.has(id)),
				suggestions: group.suggestions.map((item) => item.name).filter((name) => name)
			}))
			.filter((group) => group.ids.length);
		const listed = new Set(grouped.flatMap((group) => group.ids));
		const alone = (await this.#records([...unnamed].filter((id) => !listed.has(id))))
			.sort((a, b) => b.seen.localeCompare(a.seen))
			.map((sighting) => ({ ids: [sighting.id], suggestions: [] }));
		const all = [...grouped, ...alone];
		const groups: SightingGroup[] = await Promise.all(
			all.slice(0, GROUPS_SHOWN).map(async (group) => ({
				...group,
				shown: await this.#records(group.ids.slice(0, PICTURES_SHOWN))
			}))
		);
		return { groups, moreGroups: Math.max(0, all.length - GROUPS_SHOWN) };
	}

	async overview(): Promise<IndividualsOverview> {
		const [ids, names] = await Promise.all([this.#sightingIds(), this.#readNames()]);
		const unnamed = new Set(ids.filter((id) => !(id in names)));
		const { groups, moreGroups } = await this.#groups(unnamed);
		const named = await this.#records(Object.keys(names));
		const byName = new Map<string, Sighting[]>();
		for (const sighting of named.sort((a, b) => b.seen.localeCompare(a.seen)))
			byName.set(names[sighting.id], [...(byName.get(names[sighting.id]) ?? []), sighting]);
		const individuals: NamedIndividual[] = [...byName]
			.map(([name, sightings]) => ({
				name,
				ids: sightings.map((sighting) => sighting.id),
				shown: sightings.slice(0, PICTURES_SHOWN)
			}))
			.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
		return {
			groups,
			moreGroups,
			unnamed: unnamed.size,
			named: individuals,
			namedDays: new Set(named.map((sighting) => sighting.seen.slice(0, 10))).size
		};
	}

	/** One sighting and the name a person gave it, or null once it is gone. */
	async sighting(id: string): Promise<(Sighting & { name: string | null }) | null> {
		if (!SIGHTING_ID.test(id)) return null;
		const [record, names] = await Promise.all([this.#record(id), this.#readNames()]);
		return record && { ...record, name: names[id] ?? null };
	}

	#change(update: (names: Record<string, string>) => Promise<void>): Promise<void> {
		const change = this.#changes.then(async () => {
			const names = await this.#readNames();
			await update(names);
			await writeJson(this.#names, { version: 1, names });
		});
		this.#changes = change.catch(() => undefined);
		return change;
	}

	/** Gives sightings one name; a name already given is the same individual. */
	name(sightings: string[], name: string): Promise<void> {
		return this.#change(async (names) => {
			for (const id of sightings) {
				if (!SIGHTING_ID.test(id) || !(await this.#record(id)))
					throw new SightingMissingError('A picture to name no longer exists. Reload the page.');
				names[id] = name;
			}
		});
	}

	/** Takes the names off sightings, which then wait to be named again. */
	unname(sightings: string[]): Promise<void> {
		return this.#change(async (names) => {
			for (const id of sightings) delete names[id];
		});
	}

	/** Where a sighting's picture is, for a picture name such as crop-1.jpg. */
	picture(sighting: string, picture: string): string | null {
		return SIGHTING_ID.test(sighting) && PICTURE.test(picture)
			? path.join(this.#sighting(sighting), picture)
			: null;
	}
}

import { appendFile, mkdir, readdir, readFile, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import {
	watchStretches,
	type WatchChange,
	type WatchState,
	type WatchStretch
} from '../camera-history.ts';
import { isMissingFile } from './archive.ts';

const DAYS_KEPT = 30;

/** The calendar day of a moment on this computer, as in the names of recordings. */
function day(moment: Date): string {
	const pad = (value: number) => String(value).padStart(2, '0');
	return `${moment.getFullYear()}-${pad(moment.getMonth() + 1)}-${pad(moment.getDate())}`;
}

/**
 * When each camera was really watched. Every change of a camera's state is one line in the
 * file of its day, and each day's file starts with the states the day began in, so a day can
 * be read by itself. `alive` holds the last moment the application was running: what follows
 * it until the next start is time nothing was watched.
 */
export class WatchHistory {
	private readonly directory: string;
	private states = new Map<string, WatchState>();
	private today = '';

	constructor(directory: string) {
		this.directory = directory;
	}

	private file(name: string): string {
		return path.join(this.directory, name);
	}

	private async changes(name: string): Promise<WatchChange[]> {
		try {
			const text = await readFile(this.file(`${name}.jsonl`), 'utf8');
			return text
				.split('\n')
				.filter(Boolean)
				.map((line) => JSON.parse(line) as WatchChange);
		} catch (error) {
			if (isMissingFile(error)) return [];
			throw error;
		}
	}

	private async alive(): Promise<Date | undefined> {
		try {
			return new Date(await readFile(this.file('alive'), 'utf8'));
		} catch (error) {
			if (isMissingFile(error)) return undefined;
			throw error;
		}
	}

	/** Close what was open when the application last stopped, however it stopped. */
	async start(): Promise<void> {
		await mkdir(this.directory, { recursive: true });
		const stopped = await this.alive();
		if (!stopped) return;
		this.today = day(stopped);
		for (const change of await this.changes(this.today))
			this.states.set(change.camera, change.state);
		await this.write(
			Array.from(this.states.keys(), (camera) => ({ camera, state: 'stopped' as const })),
			stopped
		);
	}

	/** Keep the state of every camera at this moment; cameras no longer listed have stopped. */
	async sample(cameras: { id: string; state: WatchState }[], now = new Date()): Promise<void> {
		if (day(now) !== this.today) {
			const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate());
			const carried = Array.from(this.states, ([camera, state]) => ({ camera, state }));
			this.states.clear();
			this.today = day(now);
			await this.write(carried, midnight);
			await this.prune(now);
		}
		const listed = new Set(cameras.map((camera) => camera.id));
		await this.write(
			[
				...cameras.map(({ id, state }) => ({ camera: id, state })),
				...Array.from(this.states.keys())
					.filter((camera) => !listed.has(camera))
					.map((camera) => ({ camera, state: 'stopped' as const }))
			],
			now
		);
		for (const camera of this.states.keys()) if (!listed.has(camera)) this.states.delete(camera);
		await writeFile(this.file('alive'), now.toISOString());
	}

	private async write(states: { camera: string; state: WatchState }[], at: Date): Promise<void> {
		const changed = states.filter(({ camera, state }) => this.states.get(camera) !== state);
		if (!changed.length) return;
		const lines = changed.map((change) => JSON.stringify({ at: at.toISOString(), ...change }));
		await appendFile(this.file(`${this.today}.jsonl`), lines.join('\n') + '\n');
		for (const { camera, state } of changed) this.states.set(camera, state);
	}

	private async prune(now: Date): Promise<void> {
		const oldest = day(new Date(now.getTime() - DAYS_KEPT * 86400000));
		for (const name of await readdir(this.directory))
			if (name.endsWith('.jsonl') && name.slice(0, 10) < oldest) await rm(this.file(name));
	}

	async read(from: Date, to: Date): Promise<Map<string, WatchStretch[]>> {
		const changes: WatchChange[] = [];
		const last = day(to);
		for (
			let date = new Date(from.getFullYear(), from.getMonth(), from.getDate());
			day(date) <= last;
			date.setDate(date.getDate() + 1)
		)
			changes.push(...(await this.changes(day(date))));
		return watchStretches(changes, from, to, (await this.alive()) ?? from);
	}
}

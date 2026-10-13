import path from 'node:path';
import { isDeepStrictEqual } from 'node:util';
import { readJson, writeJson } from './json-file.ts';
import { serialQueue } from './serial.ts';

const queues = new Map<string, ReturnType<typeof serialQueue>>();

/**
 * One whole-file replacement at a time. The settings store and the detector launcher both
 * rewrite app.json; each holds this only for its own file work, never while waiting for the other.
 */
export function exclusiveWrite<T>(file: string, operation: () => Promise<T>): Promise<T> {
	const key = path.resolve(file);
	const queue = queues.get(key) ?? serialQueue();
	queues.set(key, queue);
	return queue(operation);
}

/**
 * What the detector launcher notes in app.json: `monitoring`, whether monitoring resumes when
 * the application starts, and `outages`, the cameras people were warned about and since when.
 * Both stay with this installation, like paired devices: the settings store carries them over
 * untouched and never exports, imports or recovers them.
 */
export async function launcherNotes(
	appFile: string
): Promise<{ monitoring?: unknown; outages?: unknown }> {
	const { monitoring, outages } = (await readJson<Record<string, unknown>>(appFile)) ?? {};
	return {
		...(monitoring !== undefined && { monitoring }),
		...(outages !== undefined && { outages })
	};
}

export async function monitoringEnabled(appFile: string): Promise<boolean> {
	return (await launcherNotes(appFile)).monitoring === true;
}

function note(appFile: string, key: 'monitoring' | 'outages', value: unknown): Promise<void> {
	return exclusiveWrite(appFile, async () => {
		const app = (await readJson<Record<string, unknown>>(appFile)) ?? {};
		// Nothing to change; in particular, a new installation gets no settings file for "off".
		if (isDeepStrictEqual(app[key], value)) return;
		if (value === undefined) delete app[key];
		else app[key] = value;
		await writeJson(appFile, app);
	});
}

export function setMonitoringEnabled(appFile: string, enabled: boolean): Promise<void> {
	return note(appFile, 'monitoring', enabled ? true : undefined);
}

/** Each camera people were warned about, with the moment it was last watched. */
export function noteOutages(appFile: string, outages: Record<string, string>): Promise<void> {
	return note(appFile, 'outages', Object.keys(outages).length ? outages : undefined);
}

import path from 'node:path';
import { readJson, writeJson } from './json-file.ts';

const writers = new Map<string, Promise<unknown>>();

/**
 * One whole-file replacement at a time. The settings store and the detector launcher both
 * rewrite app.json; each holds this only for its own file work, never while waiting for the other.
 */
export function exclusiveWrite<T>(file: string, operation: () => Promise<T>): Promise<T> {
	const key = path.resolve(file);
	const result = (writers.get(key) ?? Promise.resolve()).then(operation);
	const settled = result.catch(() => undefined);
	writers.set(key, settled);
	void settled.then(() => {
		if (writers.get(key) === settled) writers.delete(key);
	});
	return result;
}

/**
 * `monitoring` in app.json: whether monitoring resumes when the application starts. It belongs
 * to the detector launcher and stays with this installation, like paired devices: the settings
 * store carries it over untouched and never exports, imports or recovers it.
 */
export async function monitoringEnabled(appFile: string): Promise<boolean> {
	return (await readJson<{ monitoring?: unknown }>(appFile))?.monitoring === true;
}

export function setMonitoringEnabled(appFile: string, enabled: boolean): Promise<void> {
	return exclusiveWrite(appFile, async () => {
		const app = (await readJson<Record<string, unknown>>(appFile)) ?? {};
		// Nothing to change; in particular, a new installation gets no settings file for "off".
		if ((app.monitoring === true) === enabled) return;
		if (enabled) app.monitoring = true;
		else delete app.monitoring;
		await writeJson(appFile, app);
	});
}

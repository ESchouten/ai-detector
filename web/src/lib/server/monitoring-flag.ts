import path from 'node:path';
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

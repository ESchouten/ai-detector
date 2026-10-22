import { uniqueLabel } from '../../configuration.ts';

function isRecord(value: unknown): value is Record<string, unknown> {
	return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isEmpty(value: unknown): boolean {
	return value == null || (typeof value === 'string' && value.trim() === '');
}

function omitEmpty(record: Record<string, unknown>, keys: readonly string[]): boolean {
	let changed = false;
	for (const key of keys) {
		if (Object.hasOwn(record, key) && isEmpty(record[key])) {
			delete record[key];
			changed = true;
		}
	}
	return changed;
}

function nameEntries(entries: unknown[], prefix: string): boolean {
	const labels = new Set(
		entries.flatMap((entry) =>
			isRecord(entry) && typeof entry.label === 'string' && entry.label.trim()
				? [entry.label.trim()]
				: []
		)
	);
	let changed = false;
	for (const [index, entry] of entries.entries()) {
		if (isRecord(entry) && isEmpty(entry.label)) {
			entry.label = uniqueLabel(`${prefix} ${index + 1}`, labels);
			changed = true;
		}
	}
	return changed;
}

function migrateEntries(value: unknown, prefix: string, optional: readonly string[]): boolean {
	if (!Array.isArray(value)) return false;
	let changed = nameEntries(value, prefix);
	for (const entry of value) {
		if (isRecord(entry)) changed = omitEmpty(entry, optional) || changed;
	}
	return changed;
}

function resetCameraMetadata(value: unknown): boolean {
	if (!Array.isArray(value)) return false;
	let changed = false;
	for (const camera of value) {
		if (!isRecord(camera)) continue;
		// Verification belongs to this installation and is repeated after importing.
		delete camera.setup;
		changed = omitEmpty(camera, ['connection']) || changed;
		if (isRecord(camera.connection))
			changed = omitEmpty(camera.connection, ['profileToken']) || changed;
	}
	return changed;
}

/** Only import treats empty names and optional metadata as unset; saved settings stay strict. */
export function migrateAppMetadata(input: unknown, notes: string[]): unknown {
	const app = input === null ? {} : input;
	if (!isRecord(app)) return app;
	let changed = input === null || omitEmpty(app, ['language']);
	const groups = [
		['streams', 'Camera', ['id']],
		['detectors', 'Detector', ['preset', 'mode', 'presetVersion', 'llmConnection']],
		['telegrams', 'Telegram', []],
		['llms', 'AI connection', ['url']]
	] as const;
	for (const [key, prefix, optional] of groups) {
		if (app[key] === null) {
			delete app[key];
			changed = true;
		} else {
			changed = migrateEntries(app[key], prefix, optional) || changed;
		}
	}
	changed = resetCameraMetadata(app.streams) || changed;
	// Paired devices never transfer to another installation, even if their old format differs.
	delete app.devices;
	if (changed)
		notes.push('Filled in missing names and ignored empty optional settings in app.json.');
	return app;
}

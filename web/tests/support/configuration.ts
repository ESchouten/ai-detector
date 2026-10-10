import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import type { TestContext } from 'node:test';
import { ConfigurationStore } from '../../src/lib/server/configuration/store.ts';
import type { StreamMeta } from '../../src/lib/schema.ts';
import { readTestPresets } from './presets.ts';

type StoreArguments = ConstructorParameters<typeof ConfigurationStore>;

/** A store over settings files in a folder of its own, which is removed after the test. */
export async function settingsStore(
	t: TestContext,
	runtime?: StoreArguments[1],
	language?: StoreArguments[2]
) {
	const directory = await mkdtemp(path.join(tmpdir(), 'detector-settings-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	const files = {
		config: path.join(directory, 'config.json'),
		app: path.join(directory, 'app.json')
	};
	return { directory, files, store: new ConfigurationStore(files, runtime, language) };
}

export async function addPresetDetector(
	store: ConfigurationStore,
	camera: { label: string; source: string },
	presetId: string
) {
	const preset = (await readTestPresets()).find(({ id }) => id === presetId)!;
	await store.saveDetector({
		detector: {
			...structuredClone(preset.detector),
			detection: { ...preset.detector.detection, source: [camera.source] }
		},
		meta: { label: camera.label, preset: presetId }
	});
	const saved = await store.read();
	return { id: saved.app.streams.find(({ source }) => source === camera.source)!.id! };
}

export async function addMonitoredCamera(
	store: ConfigurationStore,
	camera: { label: string; source: string; connection?: StreamMeta['connection'] },
	presetId: string,
	verifiedAt?: string
) {
	await store.saveCamera(camera, verifiedAt);
	return addPresetDetector(store, camera, presetId);
}

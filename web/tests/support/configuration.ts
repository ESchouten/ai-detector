import path from 'node:path';
import type { TestContext } from 'node:test';
import { fileURLToPath } from 'node:url';
import { loadPresets } from '../../src/lib/server/configuration/preset-files.ts';
import { ConfigurationStore } from '../../src/lib/server/configuration/store.ts';
import type { StreamMeta } from '../../src/lib/schema.ts';
import { temporaryDirectory } from './files.ts';

type StoreArguments = ConstructorParameters<typeof ConfigurationStore>;
type Runtime = NonNullable<ReturnType<NonNullable<StoreArguments[1]>>>;

export function readTestPresets() {
	return loadPresets(fileURLToPath(new URL('../../../config/detector/', import.meta.url)));
}

/** A store over settings files in a folder of its own, which is removed after the test. */
export async function settingsStore(
	t: TestContext,
	runtime?: StoreArguments[1],
	language?: StoreArguments[2]
) {
	const directory = await temporaryDirectory(t, 'detector-settings-');
	const files = {
		config: path.join(directory, 'config.json'),
		app: path.join(directory, 'app.json')
	};
	return { directory, files, store: new ConfigurationStore(files, runtime, language) };
}

/** A detector runtime that notes each step the store asks of it; tests replace what they check. */
export function fakeRuntime(steps: Partial<Runtime> = {}) {
	const calls: string[] = [];
	const runtime: Runtime = {
		validate: async () => void calls.push('validate'),
		apply: async () => void calls.push('apply'),
		stop: async () => void calls.push('stop'),
		fail: () => void calls.push('fail'),
		...steps
	};
	return { calls, runtime: () => runtime };
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

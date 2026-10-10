import type { ConfigurationStore } from '../../src/lib/server/configuration/store.ts';
import type { StreamMeta } from '../../src/lib/schema.ts';
import { readTestPresets } from './presets.ts';

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

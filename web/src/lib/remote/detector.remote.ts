import { error } from '@sveltejs/kit';
import { configurationAction } from '$lib/server/configuration/request';
import { command, query } from '$app/server';
import * as v from 'valibot';
import { configuration } from '$lib/server/configuration';
import { detectorInput } from '$lib/configuration';
import { detectorMeta } from '$lib/schema';
import { readPresets, readPresetsForSaving } from '$lib/server/configuration/presets';
import { presetFile, readPresetChoices } from '$lib/server/configuration/preset-files';

export const getDetectorPresets = query(() => readPresetChoices(readPresets));

export const getDetectorPreset = query(
	v.object({ id: v.string(), mode: v.string() }),
	({ id, mode }) =>
		configurationAction(async () => {
			const file = presetFile(id, mode);
			const preset = (await readPresets()).find((preset) => preset.id === file);
			if (!preset) error(404, 'This preset is no longer available. Choose another preset.');
			return structuredClone(preset.detector);
		})
);

export const getDetectors = query(async () => {
	const { config, app } = await configuration.read();
	return config.detectors.map((detector, index) => ({ detector, meta: app.detectors[index] }));
});

export const saveDetector = command(detectorInput, (input) =>
	configurationAction(async () => configuration.saveDetector(input, await readPresetsForSaving()))
);
export const deleteDetector = command(detectorMeta, ({ label }) =>
	configurationAction(() => configuration.deleteDetector(label))
);

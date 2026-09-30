import { error } from '@sveltejs/kit';
import { configurationAction } from '$lib/server/configuration/request';
import { command, query } from '$app/server';
import * as v from 'valibot';
import { configuration } from '$lib/server/configuration';
import { detectorInput, detectorMeta } from '$lib/configuration';
import { readPresets } from '$lib/server/configuration/presets';
import { readPresetChoices } from '$lib/server/configuration/preset-files';

export const getDetectorPresets = query(() => readPresetChoices(readPresets));

export const getDetectorPreset = query(v.object({ id: v.string() }), ({ id }) =>
	configurationAction(
		(async () => {
			const presets = await readPresets();
			const preset = presets.find((preset) => preset.id === id);
			if (!preset) error(404, 'This preset is no longer available. Choose another preset.');
			return structuredClone(preset.detector);
		})()
	)
);

export const getDetectors = query(async () => {
	const { config, app } = await configuration.read();
	return config.detectors.map((detector, index) => ({ detector, meta: app.detectors[index] }));
});

export const saveDetector = command(detectorInput, (input) =>
	configurationAction(configuration.saveDetector(input))
);
export const deleteDetector = command(detectorMeta, ({ label }) =>
	configurationAction(configuration.deleteDetector(label))
);

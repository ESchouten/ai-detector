import { error } from '@sveltejs/kit';
import { configurationAction } from '$lib/server/configuration/request';
import { command, query } from '$app/server';
import * as v from 'valibot';
import { configuration } from '$lib/server/configuration';
import { detectorInput, detectorMeta } from '$lib/configuration';
import { readPresetCatalog } from '$lib/server/configuration/presets';
import { readPresetChoices } from '$lib/server/configuration/preset-catalog';
import { getEditorSchema } from '$lib/server/configuration/editor-schema';

export const getDetectorPresets = query(() => readPresetChoices(readPresetCatalog));

export const getDetectorPreset = query(v.object({ id: v.string() }), ({ id }) =>
	configurationAction(
		(async () => {
			const catalog = await readPresetCatalog();
			const preset = catalog.presets.find((preset) => preset.id === id);
			if (!preset) error(404, 'This preset is no longer available. Choose another preset.');
			return structuredClone(preset.detector);
		})()
	)
);

export const getDetectorSchema = query(async () => {
	const { config } = await configuration.read();
	const schema = await getEditorSchema(config.$schema);
	return { $defs: schema.$defs, ...schema.$defs.DetectorConfig };
});

export const getDetectors = query(async () => {
	const { config, app } = await configuration.read();
	return config.detectors.map((detector, index) => ({ detector, meta: app.detectors[index] }));
});

export const getDetector = query(detectorMeta, async ({ label }) => {
	const { config, app } = await configuration.read();
	const index = app.detectors.findIndex((meta) => meta.label === label);
	return index < 0 ? undefined : { detector: config.detectors[index], meta: app.detectors[index] };
});

export const saveDetector = command(detectorInput, (input) =>
	configurationAction(configuration.saveDetector(input))
);
export const deleteDetector = command(detectorMeta, ({ label }) =>
	configurationAction(configuration.deleteDetector(label))
);

import path from 'node:path';
import { DATA_DIRECTORY } from '../application-paths.ts';
import { loadPresets } from './preset-files.ts';

const bundledConfigurations = import.meta.glob('../../../../../config/detector/*.json', {
	eager: true,
	import: 'default'
});

export function readPresets() {
	const override = process.env.AIDETECTOR_PRESETS;
	const directory = override ? path.resolve(override) : path.join(DATA_DIRECTORY, 'presets');
	return loadPresets(directory, override ? undefined : bundledConfigurations);
}

import path from 'node:path';
import { DATA_DIRECTORY } from '../application-paths.ts';
import { webLog } from '../web-log.ts';
import { configuration } from './index.ts';
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

/**
 * A new release may bring presets with a newer model. Detectors that follow one take it here,
 * before monitoring starts; when that fails they keep the settings they have.
 */
export async function updateFollowedPresets(): Promise<void> {
	try {
		for (const label of await configuration.followPresets(await readPresets()))
			console.info(`Detector "${label}" now has the current settings of its preset.`);
	} catch (error) {
		webLog.warn('Could not bring detectors up to date with their presets.', error);
	}
}

import { fileURLToPath } from 'node:url';
import { loadPresetCatalog } from '../../src/lib/server/configuration/preset-catalog.ts';

export function readTestPresets() {
	return loadPresetCatalog(fileURLToPath(new URL('../../../config/presets.json', import.meta.url)));
}

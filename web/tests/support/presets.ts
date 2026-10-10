import { fileURLToPath } from 'node:url';
import { loadPresets } from '../../src/lib/server/configuration/preset-files.ts';

export function readTestPresets() {
	return loadPresets(fileURLToPath(new URL('../../../config/detector/', import.meta.url)));
}

import path from 'node:path';
import catalog from '../../../../../config/presets.json' with { type: 'json' };
import { ConfigurationError } from '../../configuration.ts';
import { DATA_DIRECTORY } from '../application-paths.ts';
import { readPresetJson, resolvePresetCatalog } from './preset-catalog.ts';

const bundledConfigurations = import.meta.glob('../../../../../config/detector/*.json', {
	eager: true,
	import: 'default'
});

export async function readPresetCatalog() {
	const override = process.env.AIDETECTOR_PRESETS;
	const file = override ? path.resolve(override) : path.join(DATA_DIRECTORY, 'presets.json');
	const definition = await readPresetJson(file, !override);
	if (definition === undefined) {
		return resolvePresetCatalog(catalog, async (configuration) => {
			const key = `../../../../../config/${configuration}`;
			if (!Object.hasOwn(bundledConfigurations, key))
				throw new ConfigurationError(`Bundled preset configuration "${configuration}" is missing.`);
			return bundledConfigurations[key];
		});
	}
	return resolvePresetCatalog(definition, (configuration) =>
		readPresetJson(path.resolve(path.dirname(file), configuration))
	);
}

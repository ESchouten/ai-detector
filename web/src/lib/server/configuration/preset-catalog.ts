import { readFile } from 'node:fs/promises';
import path from 'node:path';
import * as v from 'valibot';
import { ConfigurationError, normalizeConfig } from '../../configuration.ts';
import type { DetectorConfig, PresetCatalog, PresetInfo } from '../../schema.ts';

/** Optional editor choices remain available as a warning when an external template is invalid. */
export async function readPresetChoices(read: () => Promise<PresetCatalog>): Promise<{
	catalogue: { defaultPreset?: string; presets: PresetInfo[] };
	warning?: string;
}> {
	try {
		const catalog = await read();
		return {
			catalogue: {
				defaultPreset: catalog.defaultPreset,
				presets: catalog.presets.map(({ id, name, description, guidance }) => ({
					id,
					name,
					description,
					guidance
				}))
			}
		};
	} catch (cause) {
		if (!(cause instanceof ConfigurationError)) throw cause;
		return { catalogue: { presets: [] }, warning: cause.message };
	}
}

const text = v.pipe(v.string(), v.trim(), v.minLength(1));
const catalogSchema = v.strictObject({
	defaultPreset: v.optional(text),
	presets: v.array(
		v.strictObject({
			id: text,
			name: text,
			description: text,
			guidance: v.optional(text),
			configuration: text
		})
	)
});

function detectorTemplate(input: unknown): DetectorConfig {
	const parsed = v.safeParse(v.looseObject({ detection: v.optional(v.looseObject({})) }), input);
	if (!parsed.success)
		throw new ConfigurationError('A preset must contain a detector configuration.');
	// Bind a source only for canonical validation; choosing a camera supplies its real source.
	const detector = normalizeConfig({
		detectors: [
			{
				...parsed.output,
				detection: { ...parsed.output.detection, source: ['rtsp://preset.invalid/stream'] }
			}
		]
	}).detectors[0];
	detector.detection.source = [];
	return detector;
}

export async function resolvePresetCatalog(
	input: unknown,
	readConfiguration: (file: string) => Promise<unknown>
): Promise<PresetCatalog> {
	const parsed = v.safeParse(catalogSchema, input);
	if (!parsed.success)
		throw new ConfigurationError(`Invalid preset catalogue: ${parsed.issues[0].message}`);
	const { defaultPreset, presets } = parsed.output;
	const ids = new Set(presets.map(({ id }) => id));
	if (ids.size !== presets.length) throw new ConfigurationError('Preset IDs must be unique.');
	if (defaultPreset && !ids.has(defaultPreset))
		throw new ConfigurationError('The default preset must name an entry in the preset catalogue.');
	return {
		...(defaultPreset ? { defaultPreset } : {}),
		presets: await Promise.all(
			presets.map(async ({ configuration, ...info }) => ({
				...info,
				detector: detectorTemplate(await readConfiguration(configuration))
			}))
		)
	};
}

export async function readPresetJson(file: string, optional = false): Promise<unknown> {
	let contents: string;
	try {
		contents = await readFile(file, 'utf8');
	} catch (error) {
		if (optional && (error as NodeJS.ErrnoException).code === 'ENOENT') return undefined;
		throw new ConfigurationError(
			`Could not read preset file "${file}". Check the file path and access permissions.`,
			{ cause: error }
		);
	}
	try {
		return JSON.parse(contents);
	} catch (error) {
		if (error instanceof SyntaxError)
			throw new ConfigurationError(`Preset file "${file}" is not valid JSON.`);
		throw error;
	}
}

export async function loadPresetCatalog(file: string): Promise<PresetCatalog> {
	return resolvePresetCatalog(await readPresetJson(file), (configuration) =>
		readPresetJson(path.resolve(path.dirname(file), configuration))
	);
}

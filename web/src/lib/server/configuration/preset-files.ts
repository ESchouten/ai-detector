import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import * as v from 'valibot';
import { ConfigurationError, normalizeConfig } from '../../configuration.ts';
import type { DetectorConfig, DetectorPreset, PresetInfo } from '../../schema.ts';

/** Invalid templates must not prevent editing a detector's saved settings. */
export async function readPresetChoices(read: () => Promise<DetectorPreset[]>): Promise<{
	presets: PresetInfo[];
	warning?: string;
}> {
	try {
		return { presets: (await read()).map(({ id, name }) => ({ id, name })) };
	} catch (cause) {
		if (!(cause instanceof ConfigurationError)) throw cause;
		return { presets: [], warning: cause.message };
	}
}

function detectorTemplate(input: unknown): DetectorConfig {
	const parsed = v.safeParse(v.looseObject({ detection: v.optional(v.looseObject({})) }), input);
	if (
		!parsed.success ||
		Array.isArray(input) ||
		Array.isArray((input as { detection?: unknown }).detection)
	)
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

function presetFromFile(file: string, input: unknown): DetectorPreset {
	const id = path.basename(file, '.json');
	const name = id
		.split(/[-_\s]+/)
		.map((word) => word.charAt(0).toUpperCase() + word.slice(1))
		.join(' ');
	try {
		return { id, name, detector: detectorTemplate(input) };
	} catch (cause) {
		if (!(cause instanceof ConfigurationError)) throw cause;
		throw new ConfigurationError(`Invalid preset "${file}": ${cause.message}`, { cause });
	}
}

async function readPresetFile(file: string): Promise<DetectorPreset> {
	let contents: string;
	try {
		contents = await readFile(file, 'utf8');
	} catch (cause) {
		throw new ConfigurationError(`Could not read preset file "${file}".`, { cause });
	}
	let input: unknown;
	try {
		input = JSON.parse(contents);
	} catch (cause) {
		if (!(cause instanceof SyntaxError)) throw cause;
		throw new ConfigurationError(`Preset file "${file}" is not valid JSON.`, { cause });
	}
	return presetFromFile(file, input);
}

export async function loadPresets(
	directory: string,
	bundled?: Record<string, unknown>
): Promise<DetectorPreset[]> {
	let entries;
	try {
		entries = await readdir(directory, { withFileTypes: true });
	} catch (cause) {
		if ((cause as NodeJS.ErrnoException).code === 'ENOENT' && bundled) {
			return Object.entries(bundled)
				.sort(([a], [b]) => a.localeCompare(b, 'en'))
				.map(([file, input]) => presetFromFile(file, input));
		}
		throw new ConfigurationError(`Could not read preset folder "${directory}".`, { cause });
	}
	const files = entries
		.filter((entry) => entry.isFile() && entry.name.endsWith('.json'))
		.map((entry) => entry.name)
		.sort((a, b) => a.localeCompare(b, 'en'));
	return Promise.all(files.map((file) => readPresetFile(path.join(directory, file))));
}

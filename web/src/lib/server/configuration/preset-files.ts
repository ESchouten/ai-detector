import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import * as v from 'valibot';
import { ConfigurationError, normalizeConfig } from '../../configuration.ts';
import type { DetectorPreset, PresetInfo, TelegramSettings } from '../../schema.ts';

/** A file name as people read it: `cow-catcher` is Cow Catcher, `low-power` is Low Power. */
function readableName(id: string): string {
	return id
		.split(/[-_.\s]+/)
		.map((word) => word.charAt(0).toUpperCase() + word.slice(1))
		.join(' ');
}

/** The preset file a detector follows: its preset's, or that of one of the preset's modes. */
export function presetFile(id: string, mode?: string): string {
	return mode ? `${id}.${mode}` : id;
}

/** A file `<preset>.<mode>` beside its preset is one of that preset's modes. */
function presetMode(id: string, ids: Set<string>): { preset: string; mode: string } | undefined {
	const { name, ext } = path.parse(id);
	return ext && ids.has(name) ? { preset: name, mode: ext.slice(1) } : undefined;
}

/** A preset's modes are chosen with the preset, not beside it. */
function presetChoices(presets: DetectorPreset[]): PresetInfo[] {
	const ids = new Set(presets.map(({ id }) => id));
	const modes = presets.flatMap(({ id }) => presetMode(id, ids) ?? []);
	return presets
		.filter(({ id }) => !presetMode(id, ids))
		.map(({ id, name }) => {
			const own = modes
				.filter(({ preset }) => preset === id)
				.map(({ mode }) => ({ id: mode, name: readableName(mode) }));
			return { id, name, ...(own.length > 0 && { modes: own }) };
		});
}

/** Invalid templates must not prevent editing a detector's saved settings. */
export async function readPresetChoices(read: () => Promise<DetectorPreset[]>): Promise<{
	presets: PresetInfo[];
	warning?: string;
}> {
	try {
		return { presets: presetChoices(await read()) };
	} catch (cause) {
		if (!(cause instanceof ConfigurationError)) throw cause;
		return { presets: [], warning: cause.message };
	}
}

/** Each recipient's own; a preset sets the rest of its Telegram alerts. */
const RECIPIENT = ['token', 'chat', 'quiet'];

function presetSettings(input: unknown): Pick<DetectorPreset, 'detector' | 'telegram'> {
	const parsed = v.safeParse(
		v.looseObject({
			detection: v.optional(v.looseObject({})),
			exporters: v.optional(v.looseObject({ telegram: v.optional(v.looseObject({})) }))
		}),
		input
	);
	const raw = input as { detection?: unknown; exporters?: { telegram?: unknown } };
	if (
		!parsed.success ||
		[input, raw.detection, raw.exporters, raw.exporters?.telegram].some(Array.isArray)
	)
		throw new ConfigurationError('A preset must contain a detector configuration.');
	const { telegram, ...exporters } = parsed.output.exporters ?? {};
	if (telegram && RECIPIENT.some((key) => key in telegram))
		throw new ConfigurationError(
			'Telegram settings in a preset leave out token, chat and quiet: each recipient has its own.'
		);
	// Bind a source and a recipient only for canonical validation; choosing a camera supplies its
	// real source, and each recipient its own bot and chat.
	const detector = normalizeConfig({
		detectors: [
			{
				...parsed.output,
				detection: { ...parsed.output.detection, source: ['rtsp://preset.invalid/stream'] },
				exporters: telegram
					? { ...exporters, telegram: { ...telegram, token: 'preset', chat: 'preset' } }
					: exporters
			}
		]
	}).detectors[0];
	detector.detection.source = [];
	delete detector.exporters?.telegram;
	return { detector, ...(telegram && { telegram: telegram as TelegramSettings }) };
}

export function presetFromFile(file: string, input: unknown): DetectorPreset {
	const id = path.basename(file, '.json');
	try {
		return { id, name: readableName(id), ...presetSettings(input) };
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
	bundled: Record<string, unknown>
): Promise<DetectorPreset[]> {
	let entries;
	try {
		entries = await readdir(directory, { withFileTypes: true });
	} catch (cause) {
		if ((cause as NodeJS.ErrnoException).code === 'ENOENT') {
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

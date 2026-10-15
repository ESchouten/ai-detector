import { createHash } from 'node:crypto';
import { isDeepStrictEqual } from 'node:util';
import { detectorSettings } from '../../configuration.ts';
import type {
	Configuration,
	DetectorConfig,
	DetectorMeta,
	DetectorPreset,
	TelegramSettings
} from '../../schema.ts';
import { presetFile } from './preset-files.ts';

/** Object keys in order, so that two spellings of the same settings are one version. */
function ordered(_key: string, value: unknown): unknown {
	if (value === null || typeof value !== 'object' || Array.isArray(value)) return value;
	const settings = value as Record<string, unknown>;
	return Object.fromEntries(
		Object.keys(settings)
			.sort()
			.map((key) => [key, settings[key]])
	);
}

/**
 * Names the detection settings a preset gives. A detector keeps the version it was given, which
 * tells later whether it still has those settings and whether the preset has moved on.
 */
export function presetVersion(detector: DetectorConfig): string {
	return createHash('sha256')
		.update(JSON.stringify(detectorSettings(detector), ordered))
		.digest('hex');
}

/** A detector with settings of its own follows no preset. */
export function forgetPreset(meta: DetectorMeta): void {
	delete meta.preset;
	delete meta.mode;
	delete meta.presetVersion;
}

/** A detector whose detection settings were changed outside this application follows no preset. */
export function forgetChangedPresets(document: Configuration): Configuration {
	for (const [index, meta] of document.app.detectors.entries()) {
		if (meta.preset && meta.presetVersion !== presetVersion(document.config.detectors[index]))
			forgetPreset(meta);
	}
	return document;
}

function follows(meta: DetectorMeta, preset: DetectorPreset): boolean {
	return meta.preset !== undefined && presetFile(meta.preset, meta.mode) === preset.id;
}

/** What the preset a detector follows sets for its Telegram alerts. */
export function presetTelegram(
	meta: DetectorMeta,
	presets: DetectorPreset[]
): TelegramSettings | undefined {
	return presets.find((preset) => follows(meta, preset))?.telegram;
}

/** The detector with what its preset sets for Telegram alerts in place of their defaults. */
export function withPresetTelegram(
	detector: DetectorConfig,
	telegram?: TelegramSettings
): DetectorConfig {
	const recipients = detector.exporters?.telegram;
	if (!telegram || !recipients) return detector;
	return {
		...detector,
		exporters: {
			...detector.exporters,
			telegram: recipients.map((recipient) => ({ ...recipient, ...telegram }))
		}
	};
}

/** Whether the preset has detection or Telegram settings that the detector lacks. */
function behind(meta: DetectorMeta, detector: DetectorConfig, preset: DetectorPreset): boolean {
	return (
		meta.presetVersion !== presetVersion(preset.detector) ||
		!isDeepStrictEqual(withPresetTelegram(detector, preset.telegram), detector)
	);
}

/** The presets that would change a detector that follows them. */
export function newerPresets(
	{ config, app }: Configuration,
	presets: DetectorPreset[]
): DetectorPreset[] {
	return presets.filter((preset) =>
		app.detectors.some(
			(meta, index) =>
				follows(meta, preset) &&
				meta.autoUpdate !== false &&
				behind(meta, config.detectors[index], preset)
		)
	);
}

/**
 * Give each detector that follows a preset the preset's current detection and Telegram settings,
 * unless the person switched that off for it. Its cameras, recipients, other delivery and
 * verification stay as saved. Returns the names of the detectors that changed.
 */
export function followPresets({ config, app }: Configuration, presets: DetectorPreset[]): string[] {
	const updated: string[] = [];
	for (const [index, meta] of app.detectors.entries()) {
		const preset = presets.find((item) => follows(meta, item));
		const saved = config.detectors[index];
		if (!preset || meta.autoUpdate === false || !behind(meta, saved, preset)) continue;
		config.detectors[index] = withPresetTelegram(
			{
				...preset.detector,
				detection: { ...preset.detector.detection, source: saved.detection.source },
				vlm: saved.vlm,
				exporters: saved.exporters
			},
			preset.telegram
		);
		meta.presetVersion = presetVersion(preset.detector);
		updated.push(meta.label);
	}
	return updated;
}

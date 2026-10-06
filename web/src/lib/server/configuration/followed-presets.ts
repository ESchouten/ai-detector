import { createHash } from 'node:crypto';
import { detectorSettings } from '../../configuration.ts';
import type { Configuration, DetectorConfig, DetectorPreset } from '../../schema.ts';

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

/**
 * A detector whose detection settings were changed outside this application follows no preset.
 * One saved before versions were recorded is left for `followPresets` to judge.
 */
export function forgetChangedPresets(document: Configuration): Configuration {
	for (const [index, meta] of document.app.detectors.entries()) {
		if (
			meta.presetVersion &&
			meta.presetVersion !== presetVersion(document.config.detectors[index])
		) {
			delete meta.preset;
			delete meta.presetVersion;
		}
	}
	return document;
}

/** The presets that would change a detector that follows them. */
export function newerPresets({ app }: Configuration, presets: DetectorPreset[]): DetectorPreset[] {
	return presets.filter((preset) =>
		app.detectors.some(
			(meta) =>
				meta.preset === preset.id &&
				meta.autoUpdate !== false &&
				meta.presetVersion !== presetVersion(preset.detector)
		)
	);
}

/**
 * Give each detector that follows a preset the preset's current detection settings, unless the
 * person switched that off for it. Its cameras, delivery and verification stay as saved. Returns
 * the names of the detectors that changed.
 */
export function followPresets({ config, app }: Configuration, presets: DetectorPreset[]): string[] {
	const updated: string[] = [];
	for (const [index, meta] of app.detectors.entries()) {
		const preset = presets.find(({ id }) => id === meta.preset)?.detector;
		if (!preset || meta.autoUpdate === false || presetVersion(preset) === meta.presetVersion)
			continue;
		const saved = config.detectors[index];
		if (!meta.presetVersion) {
			// Saved before versions were recorded: it follows only if it has the preset's settings now.
			if (presetVersion(saved) === presetVersion(preset))
				meta.presetVersion = presetVersion(preset);
			else delete meta.preset;
			continue;
		}
		config.detectors[index] = {
			...preset,
			detection: { ...preset.detection, source: saved.detection.source },
			vlm: saved.vlm,
			exporters: saved.exporters
		};
		meta.presetVersion = presetVersion(preset);
		updated.push(meta.label);
	}
	return updated;
}

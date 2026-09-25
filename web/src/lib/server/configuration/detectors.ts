import { isDeepStrictEqual } from 'node:util';
import type * as v from 'valibot';
import {
	ConfigurationError,
	detectorInput,
	detectorSettings,
	normalizeConfig
} from '../../configuration.ts';
import type { Configuration } from '../../schema.ts';

export function saveDetector(
	{ config, app }: Configuration,
	input: v.InferOutput<typeof detectorInput>
): void {
	const index = input.original
		? app.detectors.findIndex((item) => item.label === input.original)
		: -1;
	if (input.original && index < 0) throw new ConfigurationError('This detector no longer exists.');
	if (app.detectors.some((item, i) => i !== index && item.label === input.meta.label)) {
		throw new ConfigurationError('A detector with this name already exists.');
	}
	const normalized = normalizeConfig({ detectors: [input.detector] }).detectors[0];
	if (index < 0) {
		config.detectors.push(normalized);
		app.detectors.push(input.meta);
		return;
	}
	const meta = { ...app.detectors[index], ...input.meta };
	if (
		!input.meta.preset &&
		!isDeepStrictEqual(detectorSettings(config.detectors[index]), detectorSettings(normalized))
	)
		delete meta.preset;
	config.detectors[index] = normalized;
	app.detectors[index] = meta;
}

export function deleteDetector({ config, app }: Configuration, label: string): void {
	const index = app.detectors.findIndex((item) => item.label === label);
	if (index < 0) throw new ConfigurationError('This detector no longer exists.');
	config.detectors.splice(index, 1);
	app.detectors.splice(index, 1);
}

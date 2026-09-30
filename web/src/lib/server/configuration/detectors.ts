import { isDeepStrictEqual } from 'node:util';
import type * as v from 'valibot';
import {
	ConfigurationError,
	detectorInput,
	detectorSettings,
	normalizeConfig
} from '../../configuration.ts';
import type { Configuration } from '../../schema.ts';
import { assignConnection } from '../../llm.ts';

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
	let normalized = normalizeConfig({ detectors: [input.detector] }).detectors[0];
	if (input.meta.llmConnection) {
		const connection = app.llms.find(({ label }) => label === input.meta.llmConnection);
		if (!connection) throw new ConfigurationError('Choose an existing AI connection.');
		const settings = normalized.vlm?.[0];
		if (!settings) throw new ConfigurationError('Enter a question for AI verification.');
		normalized = assignConnection(normalized, connection);
	}
	if (index < 0) {
		config.detectors.push(normalized);
		app.detectors.push(input.meta);
		return;
	}
	const meta = { ...app.detectors[index], ...input.meta };
	if (!input.meta.llmConnection) delete meta.llmConnection;
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

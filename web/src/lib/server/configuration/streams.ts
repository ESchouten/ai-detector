import type * as v from 'valibot';
import { ConfigurationError, streamInput } from '../../configuration.ts';
import type { Configuration } from '../../schema.ts';

export function saveStream(
	{ config, app }: Configuration,
	input: v.InferOutput<typeof streamInput>
): void {
	const index = input.original
		? app.streams.findIndex((item) => item.source === input.original)
		: -1;
	if (input.original && index < 0)
		throw new ConfigurationError('This camera source no longer exists.');
	if (app.streams.some((item, i) => i !== index && item.source === input.source)) {
		throw new ConfigurationError('This camera source already exists.');
	}
	const stream = { ...app.streams[index], label: input.label, source: input.source };
	if (input.original !== input.source) {
		stream.setup = stream.setup?.alerts ? { alerts: stream.setup.alerts } : undefined;
		delete stream.connection;
	}
	if (index < 0) app.streams.push(stream);
	else app.streams[index] = stream;
	for (const detector of config.detectors) {
		detector.detection.source = detector.detection.source.map((source) =>
			source === input.original ? input.source : source
		);
	}
}

export function deleteStream({ config, app }: Configuration, source: string): void {
	if (!app.streams.some((item) => item.source === source))
		throw new ConfigurationError('This camera source no longer exists.');
	if (
		config.detectors.some(
			(item) => item.detection.source.length === 1 && item.detection.source[0] === source
		)
	) {
		throw new ConfigurationError(
			'This camera is a detector’s only source. Update or remove that detector first.'
		);
	}
	app.streams = app.streams.filter((item) => item.source !== source);
	for (const detector of config.detectors)
		detector.detection.source = detector.detection.source.filter((item) => item !== source);
}

export function reorderStream({ app }: Configuration, index0: number, index1: number): void {
	if (
		![index0, index1].every(
			(index) => Number.isInteger(index) && index >= 0 && index < app.streams.length
		)
	) {
		throw new ConfigurationError('The camera order changed. Reload and try again.');
	}
	const [stream] = app.streams.splice(index0, 1);
	app.streams.splice(index1, 0, stream);
}

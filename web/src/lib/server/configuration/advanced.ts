import { createHash } from 'node:crypto';
import { isDeepStrictEqual } from 'node:util';
import * as v from 'valibot';
import { ConfigurationError, detectorSettings, normalizeConfig } from '../../configuration.ts';
import { llmConnection, type Configuration } from '../../schema.ts';
import { saveLlm, deleteLlm } from './llms.ts';

export function settingsRevision(document: Configuration): string {
	return createHash('sha256')
		.update(JSON.stringify({ ...document, app: { ...document.app, devices: undefined } }))
		.digest('hex');
}

export function replaceDetectorConfig(document: Configuration, input: unknown): void {
	const next = normalizeConfig(input);
	const previous = document.config.detectors;
	// Match unchanged detectors first, so a reorder or deletion keeps their names.
	const used = new Set<number>();
	const matches = next.detectors.map((detector) => {
		const index = previous.findIndex(
			(candidate, i) => !used.has(i) && isDeepStrictEqual(candidate, detector)
		);
		if (index >= 0) used.add(index);
		return index;
	});
	document.app.detectors = next.detectors.map((detector, index) => {
		const match =
			matches[index] >= 0
				? matches[index]
				: !used.has(index) && index < previous.length
					? index
					: -1;
		if (match < 0) return { label: `Detector ${index + 1}` };
		used.add(match);
		const meta = { ...document.app.detectors[match] };
		if (!isDeepStrictEqual(detectorSettings(previous[match]), detectorSettings(detector))) {
			delete meta.preset;
			delete meta.presetVersion;
		}
		return meta;
	});
	document.config = next;
}

export function replaceConnections(document: Configuration, input: unknown): void {
	const connections = v.parse(v.array(v.strictObject(llmConnection.entries)), input);
	if (new Set(connections.map(({ label }) => label)).size !== connections.length)
		throw new ConfigurationError('Each AI connection needs a unique name.');
	for (const { label } of [...document.app.llms]) {
		if (!connections.some((connection) => connection.label === label)) deleteLlm(document, label);
	}
	for (const connection of connections) {
		const existing = document.app.llms.find(({ label }) => label === connection.label);
		if (!isDeepStrictEqual(existing, connection))
			saveLlm(document, { ...connection, original: existing?.label });
	}
	document.app.llms = connections;
}

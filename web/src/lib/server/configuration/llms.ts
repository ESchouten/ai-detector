import { ConfigurationError } from '../../configuration.ts';
import { assignConnection, awaitsConnection } from '../../llm.ts';
import type { Configuration, LlmConnection } from '../../schema.ts';

export function saveLlm(
	document: Configuration,
	input: LlmConnection & { original?: string }
): void {
	const { config, app } = document;
	const index = input.original ? app.llms.findIndex(({ label }) => label === input.original) : -1;
	if (input.original && index < 0)
		throw new ConfigurationError('This AI connection no longer exists.');
	if (app.llms.some(({ label }, i) => i !== index && label === input.label))
		throw new ConfigurationError('An AI connection with this name already exists.');
	const { original, ...connection } = input;
	if (index < 0) app.llms.push(connection);
	else app.llms[index] = connection;
	for (const [i, meta] of app.detectors.entries()) {
		const detector = config.detectors[i];
		const assigned = original && meta.llmConnection === original;
		const awaitingConnection =
			!meta.llmConnection && connection.key != null && awaitsConnection(detector);
		if (!assigned && !awaitingConnection) continue;
		config.detectors[i] = assignConnection(detector, connection);
		meta.llmConnection = connection.label;
	}
}

export function deleteLlm({ app }: Configuration, label: string): void {
	if (app.detectors.some((detector) => detector.llmConnection === label))
		throw new ConfigurationError(
			'This connection is in use. Change its detectors before removing it.'
		);
	if (!app.llms.some((connection) => connection.label === label))
		throw new ConfigurationError('This AI connection no longer exists.');
	app.llms = app.llms.filter((connection) => connection.label !== label);
}

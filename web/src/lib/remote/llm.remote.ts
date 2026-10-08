import { command, query, getRequestEvent } from '$app/server';
import { error } from '@sveltejs/kit';
import * as v from 'valibot';
import { llmConnection } from '$lib/schema';
import { configuration } from '$lib/server/configuration';
import { configurationAction } from '$lib/server/configuration/request';
import { managedDetector } from '$lib/server/detector-service';
import { SetupError } from '$lib/server/runtime-platform';

export const getLlmConnections = query(async () => (await configuration.read()).app.llms);
export const canTestLlm = query(() => Boolean(managedDetector()));
export const saveLlmConnection = command(
	v.object({ ...llmConnection.entries, original: v.optional(v.string()) }),
	(input) => configurationAction(() => configuration.saveLlm(input))
);
export const deleteLlmConnection = command(v.string(), (label) =>
	configurationAction(() => configuration.deleteLlm(label))
);
export const testLlmConnection = command(llmConnection, async (connection) => {
	const runtime = managedDetector();
	if (!runtime)
		error(
			400,
			'Connection testing requires the desktop application. You can still save this connection.'
		);
	try {
		await runtime.testLlm(connection, getRequestEvent().request.signal);
	} catch (cause) {
		if (cause instanceof SetupError) error(400, cause.message);
		throw cause;
	}
	return { ok: true };
});

import { command } from '$app/server';
import { getConfig } from './config.remote';
import { saveConfig } from '$lib/server/shared-paths';
import { initialSetup, setupInput } from '$lib/server/setup-config';
import { SetupError } from '$lib/server/runtime-platform';

export const finishSetup = command(setupInput, async (input) => {
	const { config, app } = await getConfig();
	if (config.detectors.length)
		throw new SetupError('A detector is already configured. Edit it under Detectors.');
	const initial = initialSetup(input);
	await saveConfig({
		config: { ...config, ...initial.config },
		app: {
			...app,
			streams: [
				...app.streams.filter((stream) => stream.source !== input.source),
				...initial.app.streams
			],
			detectors: initial.app.detectors
		}
	});
});

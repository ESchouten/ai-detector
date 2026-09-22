import { configurationAction } from '$lib/server/configuration/request';
import { command } from '$app/server';
import { configuration } from '$lib/server/configuration';
import { setupInput } from '$lib/server/configuration/presets';

export const finishSetup = command(setupInput, (input) =>
	configurationAction(configuration.finishSetup(input))
);

import { configurationAction } from '$lib/server/configuration/request';
import { command, query } from '$app/server';
import * as v from 'valibot';
import { configuration } from '$lib/server/configuration';
import { getEditorSchema } from '$lib/server/configuration/presets';

export const getConfig = query(() => configuration.read());

export const getConfigSchema = query(async () => {
	const { config } = await configuration.read();
	return getEditorSchema(config.$schema);
});

export const saveConfig = command(v.object({ config: v.unknown(), app: v.unknown() }), (document) =>
	configurationAction(configuration.replace(document))
);

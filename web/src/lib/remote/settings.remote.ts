import { command, query } from '$app/server';
import { error } from '@sveltejs/kit';
import * as v from 'valibot';
import { parseSettings } from '$lib/advanced-settings';
import { heartbeatInput } from '$lib/configuration';
import { configuration } from '$lib/server/configuration';
import { settingsRevision } from '$lib/server/configuration/advanced';
import { configurationAction } from '$lib/server/configuration/request';

const target = v.picklist(['config', 'connections']);

export const getSettings = query(target, async (target) => {
	const document = await configuration.read();
	return {
		value: JSON.stringify(target === 'config' ? document.config : document.app.llms, null, 2),
		revision: settingsRevision(document)
	};
});

export const saveSettings = command(
	v.object({ target, text: v.string(), revision: v.string() }),
	async ({ target, text, revision }) => {
		let value: unknown;
		try {
			value = parseSettings(target, text);
		} catch (cause) {
			error(400, cause instanceof Error ? cause.message : 'Invalid JSON.');
		}
		await configurationAction(configuration.saveAdvanced(target, value, revision));
	}
);

export const getHeartbeat = query(async () => {
	const { health } = (await configuration.read()).config;
	return health ? { url: health.url, interval: health.interval ?? 60 } : null;
});

export const saveHeartbeat = command(heartbeatInput, (input) =>
	configurationAction(configuration.saveHeartbeat(input))
);

import { command, query } from '$app/server';
import { error } from '@sveltejs/kit';
import * as v from 'valibot';
import { parseSettings } from '$lib/advanced-settings';
import { configuration } from '$lib/server/configuration';
import { settingsRevision } from '$lib/server/configuration/advanced';
import { configurationAction } from '$lib/server/configuration/request';
import { managedDetector } from '$lib/server/detector-service';
import { SetupError } from '$lib/server/runtime-platform';

const target = v.picklist(['config', 'connections', 'runtime']);

export const getSettings = query(target, async (target) => {
	if (target === 'runtime') {
		const runtime = managedDetector();
		if (!runtime) error(400, 'Runtime settings require the desktop application.');
		const { mode } = runtime.status();
		return { value: JSON.stringify({ mode }, null, 2), revision: mode };
	}
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
		if (target === 'runtime') {
			const runtime = managedDetector();
			if (!runtime) error(400, 'Runtime settings require the desktop application.');
			const { mode } = v.parse(v.object({ mode: v.picklist(['auto', 'native', 'docker']) }), value);
			try {
				await runtime.setMode(mode, revision);
			} catch (cause) {
				if (cause instanceof SetupError) error(400, cause.message);
				throw cause;
			}
		} else await configurationAction(configuration.saveAdvanced(target, value, revision));
	}
);

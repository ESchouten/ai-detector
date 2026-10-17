import { configurationAction } from '$lib/server/configuration/request';
import { command, query } from '$app/server';
import * as v from 'valibot';
import { configuration } from '$lib/server/configuration';
import { readPresetsForSaving } from '$lib/server/configuration/presets';
import { alertsInput, telegramInput } from '$lib/configuration';
import { telegramMeta } from '$lib/schema';
import { sendTelegramTest } from '$lib/server/telegram';
import { telegramPairings as pairings } from '$lib/server/telegram-service';

const tokenInput = v.object({ token: v.pipe(v.string(), v.trim(), v.minLength(1)) });
const pairingInput = v.object({ id: v.pipe(v.string(), v.minLength(1)) });

export const beginTelegramPairing = command(
	v.object({
		...tokenInput.entries,
		destination: v.picklist(['private', 'group', 'channel'])
	}),
	({ token, destination }) => configurationAction(() => pairings.begin(token, destination))
);
export const pollTelegramPairing = command(pairingInput, ({ id }) =>
	configurationAction(() => pairings.poll(id))
);
export const cancelTelegramPairing = command(pairingInput, ({ id }) =>
	configurationAction(() => pairings.cancel(id))
);

export const saveAlerts = command(alertsInput, (input) =>
	configurationAction(async () => configuration.saveAlerts(input, await readPresetsForSaving()))
);
export const discoverTelegramChats = command(tokenInput, ({ token }) =>
	configurationAction(() => pairings.discoverChats(token))
);

export const getTelegrams = query(async () => (await configuration.read()).app.telegrams);

export const getOutageNotifications = query(
	async () => (await configuration.read()).app.notifyCameraOutages === true
);

export const saveOutageNotifications = command(v.boolean(), (enabled) =>
	configurationAction(() => configuration.saveOutageNotifications(enabled))
);

export const connectTelegram = command(telegramInput, (input) =>
	configurationAction(() => configuration.saveTelegram(input))
);

export const deleteTelegram = command(v.pick(telegramMeta, ['label']), ({ label }) =>
	configurationAction(() => configuration.deleteTelegram(label))
);

export const testTelegram = command(v.pick(telegramMeta, ['token', 'chat']), ({ token, chat }) =>
	configurationAction(() => sendTelegramTest(token, chat))
);

import { configurationAction } from '$lib/server/configuration/request';
import { command, form, query } from '$app/server';
import { redirect } from '@sveltejs/kit';
import * as v from 'valibot';
import { configuration } from '$lib/server/configuration';
import { alertsInput, telegramInput, telegramMeta } from '$lib/configuration';
import { sendTelegramTest } from '$lib/server/telegram';
import { TelegramPairings } from '$lib/server/telegram-pairing';

const pairings = new TelegramPairings();
const tokenInput = v.object({ token: v.pipe(v.string(), v.trim(), v.minLength(1)) });
const pairingInput = v.object({ id: v.pipe(v.string(), v.minLength(1)) });

export const beginTelegramPairing = command(tokenInput, ({ token }) =>
	configurationAction(pairings.begin(token))
);
export const pollTelegramPairing = command(pairingInput, ({ id }) =>
	configurationAction(pairings.poll(id))
);
export const cancelTelegramPairing = command(pairingInput, ({ id }) =>
	configurationAction(pairings.cancel(id))
);

export const saveAlerts = command(alertsInput, (input) =>
	configurationAction(configuration.saveAlerts(input))
);
export const discoverTelegramChats = command(tokenInput, ({ token }) =>
	configurationAction(pairings.discoverChats(token))
);

export const getTelegrams = query(async () => (await configuration.read()).app.telegrams);
export const getTelegram = query(v.pick(telegramMeta, ['label']), async ({ label }) =>
	(await configuration.read()).app.telegrams.find((telegram) => telegram.label === label)
);

export const saveTelegram = form(telegramInput, async (input) => {
	await configurationAction(configuration.saveTelegram(input));
	redirect(
		302,
		input.next?.startsWith('/') && !input.next.startsWith('//') ? input.next : '/notifications'
	);
});

export const deleteTelegram = command(v.pick(telegramMeta, ['label']), ({ label }) =>
	configurationAction(configuration.deleteTelegram(label))
);

export const testTelegram = command(
	v.pick(telegramMeta, ['token', 'chat']),
	async ({ token, chat }) => {
		await configurationAction(sendTelegramTest(token, chat));
		return { ok: true, description: 'Setup test sent.' };
	}
);

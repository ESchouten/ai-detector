import { configurationAction } from '$lib/server/configuration/request';
import { command, form, query } from '$app/server';
import { redirect } from '@sveltejs/kit';
import * as v from 'valibot';
import { configuration } from '$lib/server/configuration';
import { telegramInput, telegramMeta } from '$lib/configuration';

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
		const response = await fetch('https://api.telegram.org/bot' + token + '/sendMessage', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ chat_id: chat, text: 'Test notification' }),
			signal: AbortSignal.timeout(10000)
		});
		return response.json();
	}
);

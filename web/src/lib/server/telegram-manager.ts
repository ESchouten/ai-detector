import { env } from '$env/dynamic/private';
import * as v from 'valibot';
import QRCode from 'qrcode';
import { ConfigurationError } from '../configuration';

export function telegramManagerAvailable(): boolean {
	return Boolean(env.AI_DETECTOR_TELEGRAM_MANAGER_URL);
}
async function request(path: string, body: object) {
	const base = env.AI_DETECTOR_TELEGRAM_MANAGER_URL;
	if (!base)
		throw new ConfigurationError(
			'Automatic bot creation is not configured. Use BotFather instead.'
		);
	const url = new URL(path, base);
	if (url.protocol !== 'https:')
		throw new ConfigurationError('The Telegram manager needs an HTTPS address.');
	try {
		const response = await fetch(url, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(body),
			signal: AbortSignal.timeout(10000)
		});
		if (!response.ok) throw new Error('Manager unavailable');
		return await response.json();
	} catch {
		throw new ConfigurationError(
			'Bot creation could not connect or the link expired. Try again, or use BotFather.'
		);
	}
}
export async function beginBotCreation() {
	const session = v.parse(
		v.object({ id: v.string(), url: v.pipe(v.string(), v.url()), expiresAt: v.number() }),
		await request('/sessions', {})
	);
	const url = new URL(session.url);
	if (url.origin !== 'https://t.me')
		throw new ConfigurationError('The manager returned an invalid Telegram link.');
	return { ...session, qrDataUrl: await QRCode.toDataURL(session.url, { width: 256, margin: 4 }) };
}
export async function pollBotCreation(id: string) {
	return v.parse(
		v.variant('state', [
			v.object({ state: v.literal('waiting') }),
			v.object({ state: v.literal('created'), token: v.pipe(v.string(), v.minLength(1)) })
		]),
		await request('/poll', { id })
	);
}
export async function cancelBotCreation(id: string) {
	await request('/cancel', { id });
}

import path from 'node:path';
import { configuration } from './configuration/index.ts';
import { DATA_DIRECTORY } from './application-paths.ts';
import { recordings } from './recordings.ts';
import { TelegramInbox } from './telegram-inbox.ts';
import { TelegramPairings } from './telegram-pairing.ts';
import { reviewTelegramDetection, telegramConnections } from './telegram-reviews.ts';
import { ConfigurationError } from '../configuration.ts';

const inbox = new TelegramInbox(
	path.join(DATA_DIRECTORY, 'telegram-updates'),
	async (token, update, signal) => {
		if (!update.callback_query?.data?.startsWith('review:')) return;
		await reviewTelegramDetection(
			recordings,
			telegramConnections(await configuration.read()),
			token,
			update,
			signal
		);
	}
);
export const telegramPairings = new TelegramPairings(Date.now, inbox);

let started = false;

/** Runs with the web server, even when monitoring is paused or the browser is closed. */
export function startTelegramReviews(): void {
	if (started) return;
	started = true;
	const controller = new AbortController();
	const retries = new Map<string, number>();
	let timer: ReturnType<typeof setTimeout>;
	async function poll() {
		let delay = 1000;
		try {
			const tokens = new Set(
				telegramConnections(await configuration.read()).map(({ token }) => token)
			);
			for (const token of retries.keys()) if (!tokens.has(token)) retries.delete(token);
			await Promise.all(
				[...tokens].map(async (token) => {
					if ((retries.get(token) ?? 0) > Date.now()) return;
					try {
						await telegramPairings.receiveReviews(token, controller.signal);
						retries.delete(token);
					} catch (error) {
						retries.set(token, Date.now() + 30000);
						if (!controller.signal.aborted)
							console.warn(
								'Telegram reviews will retry in 30 seconds:',
								error instanceof ConfigurationError
									? error.message
									: 'Could not read or save a review.'
							);
					}
				})
			);
		} catch {
			delay = 30000;
			if (!controller.signal.aborted)
				console.warn('Telegram reviews: could not read settings; retrying in 30 seconds.');
		}
		if (!controller.signal.aborted) {
			timer = setTimeout(poll, delay);
			timer.unref();
		}
	}
	process.once('sveltekit:shutdown', () => {
		controller.abort();
		clearTimeout(timer);
	});
	void poll();
}

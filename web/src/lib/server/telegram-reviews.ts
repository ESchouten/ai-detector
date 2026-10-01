import type { Configuration } from '../schema.ts';
import type { DetectionArchive } from './archive.ts';
import { answerTelegramReview, type TelegramUpdate } from './telegram.ts';

export function telegramConnections({
	config,
	app
}: Configuration): { token: string; chat: string }[] {
	return [
		...app.telegrams,
		...config.detectors.flatMap((detector) => detector.exporters?.telegram ?? [])
	];
}

/** Only a connected bot/chat can change a recording. The callback identifies the event, not a file path. */
export async function reviewTelegramDetection(
	archive: DetectionArchive,
	connections: { token: string; chat: string }[],
	token: string,
	update: TelegramUpdate,
	signal?: AbortSignal
): Promise<void> {
	const callback = update.callback_query;
	const match = /^review:([a-f0-9]{32}):(approved|rejected)$/.exec(callback?.data ?? '');
	if (!callback || !match) return;
	const chat = callback.message?.chat;
	const allowed =
		!callback.from.is_bot &&
		chat &&
		connections.some(
			(connection) =>
				connection.token === token &&
				(connection.chat === String(chat.id) ||
					(chat.username && connection.chat.toLowerCase() === '@' + chat.username.toLowerCase()))
		);
	let answer: string;
	if (!allowed) answer = 'This chat is not connected to AI Detector.';
	else {
		let saved: boolean;
		try {
			saved = await archive.reviewEvent(match[1], match[2] === 'approved', 'telegram');
		} catch (error) {
			await confirmReview(
				token,
				callback.id,
				'Could not save this review. Please try again.',
				signal
			);
			throw error;
		}
		answer = saved
			? `${match[2] === 'approved' ? 'Accepted' : 'Rejected'}. Saved in AI Detector.`
			: 'This recording is no longer available in AI Detector.';
	}
	await confirmReview(token, callback.id, answer, signal);
}

async function confirmReview(
	token: string,
	callbackId: string,
	answer: string,
	signal?: AbortSignal
): Promise<void> {
	// An expired callback must not replay a saved review over a later web decision.
	try {
		await answerTelegramReview(token, callbackId, answer, signal);
	} catch {
		if (!signal?.aborted) console.warn('Telegram review confirmation could not be delivered.');
	}
}

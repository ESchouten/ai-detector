import type { InlineKeyboardMarkup } from 'grammy/types';
import type { Configuration } from '../schema.ts';
import type { DetectionArchive } from './archive.ts';
import {
	answerTelegramReview,
	showTelegramButtons,
	type PressedMessage,
	type TelegramUpdate
} from './telegram.ts';

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
	const [pressed, eventId, stage] = match;
	const approved = stage === 'approved';
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
	let saved = false;
	if (!allowed) answer = 'This chat is not connected to AI Detector.';
	else {
		try {
			saved = await archive.reviewEvent(eventId, approved, 'telegram');
		} catch (error) {
			await confirmReview(
				token,
				callback.id,
				'Could not save this review. Please try again.',
				signal
			);
			throw error;
		}
		if (!saved) answer = 'This recording is no longer available in AI Detector.';
		else
			answer = approved
				? 'Confirmed. Saved in AI Detector.'
				: 'Marked as a false alarm. Saved in AI Detector.';
	}
	await confirmReview(token, callback.id, answer, signal);
	if (saved && callback.message)
		await showReview(token, callback.message, pressed, reviewButtons(eventId, approved), signal);
}

/** The buttons the detector sends with an alert, with the saved choice coloured. */
function reviewButtons(eventId: string, approved: boolean): InlineKeyboardMarkup {
	return {
		inline_keyboard: [
			[
				{
					text: '👍',
					callback_data: `review:${eventId}:approved`,
					style: approved ? 'success' : undefined
				},
				{
					text: '👎',
					callback_data: `review:${eventId}:rejected`,
					style: approved ? undefined : 'danger'
				}
			]
		]
	};
}

/** Colours the pressed thumb on that alert, so the choice stays visible in the chat. */
async function showReview(
	token: string,
	message: PressedMessage,
	pressed: string,
	buttons: InlineKeyboardMarkup,
	signal?: AbortSignal
): Promise<void> {
	// Telegram refuses an edit that changes nothing, as when the same thumb is pressed again.
	const coloured = message.reply_markup?.inline_keyboard.flat().find((button) => button.style);
	if (coloured?.callback_data === pressed) return;
	try {
		await showTelegramButtons(token, message.chat.id, message.message_id, buttons, signal);
	} catch {
		if (!signal?.aborted) console.warn('Telegram review could not be shown on the alert.');
	}
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

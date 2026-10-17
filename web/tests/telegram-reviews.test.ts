import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { test, type TestContext } from 'node:test';
import { DetectionArchive } from '../src/lib/server/archive.ts';
import { TelegramInbox } from '../src/lib/server/telegram-inbox.ts';
import { TelegramPairings } from '../src/lib/server/telegram-pairing.ts';
import { reviewTelegramDetection } from '../src/lib/server/telegram-reviews.ts';
import type { TelegramUpdate } from '../src/lib/server/telegram.ts';
import { recordingMetadata, temporaryDirectory } from './support/files.ts';
import { confirmation, start, telegramApi } from './support/telegram.ts';

const eventId = 'a'.repeat(32);
const address = {
	type: 'activity',
	archiveStage: 'unvalidated' as const,
	timestamp: '2026-09-30T10-00-00.000000'
};
const connections = [
	{ token: 'fixture-token', chat: '123' },
	{ token: 'fixture-token', chat: '-456' }
];

/** The alert's buttons, with the thumb that Telegram shows as chosen. */
function thumbs(chosen?: 'approved' | 'rejected') {
	return {
		inline_keyboard: [
			[
				{
					text: '👍',
					callback_data: `review:${eventId}:approved`,
					...(chosen === 'approved' && { style: 'success' })
				},
				{
					text: '👎',
					callback_data: `review:${eventId}:rejected`,
					...(chosen === 'rejected' && { style: 'danger' })
				}
			]
		]
	};
}

function callback(
	update_id = 10,
	stage = 'approved',
	chat = 123,
	shown?: 'approved' | 'rejected'
): TelegramUpdate {
	return {
		update_id,
		callback_query: {
			id: 'callback-' + update_id,
			data: `review:${eventId}:${stage}`,
			from: { id: 123, is_bot: false },
			message: {
				message_id: 42,
				chat: { id: chat, type: chat > 0 ? 'private' : 'channel' },
				reply_markup: thumbs(shown)
			}
		}
	};
}

async function fixture(t: TestContext) {
	const directory = await temporaryDirectory(t, 'ai-telegram-review-');
	const root = path.join(directory, 'detections');
	const folder = path.join(root, address.type, address.archiveStage, address.timestamp);
	await mkdir(folder, { recursive: true });
	await writeFile(
		path.join(folder, 'metadata.json'),
		JSON.stringify({ ...recordingMetadata(address.timestamp), event_id: eventId, validated: null })
	);
	const archive = new DetectionArchive(root);
	const api = telegramApi(t);
	const receive = (token: string, update: TelegramUpdate, signal?: AbortSignal) =>
		reviewTelegramDetection(archive, connections, token, update, signal);
	return {
		...api,
		archive,
		receive,
		sent: (method: string) =>
			api.calls.filter((call) => call.method === method).map((call) => call.body),
		inbox: new TelegramInbox(receive)
	};
}

test('private and channel callbacks from the same bot override each other and the web reads the result', async (t) => {
	const f = await fixture(t);
	await f.receive('fixture-token', callback());
	assert.equal((await f.archive.readReview(address))?.validated, true);
	assert.match(String(f.sent('answerCallbackQuery').at(-1)?.text), /Confirmed.*Saved/);
	await f.receive('fixture-token', callback(11, 'rejected', -456));
	const recording = (await f.archive.page({ offset: 0, limit: 24 })).items[0];
	assert.equal(recording.stage, 'rejected');
	assert.equal(recording.validated, null);
	assert.equal(recording.review?.source, 'telegram');
	assert.match(String(f.sent('answerCallbackQuery').at(-1)?.text), /false alarm.*Saved/);
});

test('the pressed thumb stays coloured on that alert, and pressing it again changes nothing', async (t) => {
	const f = await fixture(t);
	await f.receive('fixture-token', callback());
	await f.receive('fixture-token', callback(11, 'approved', 123, 'approved'));
	await f.receive('fixture-token', callback(12, 'rejected', -456, 'approved'));
	assert.deepEqual(f.sent('editMessageReplyMarkup'), [
		{ chat_id: 123, message_id: 42, reply_markup: thumbs('approved') },
		{ chat_id: -456, message_id: 42, reply_markup: thumbs('rejected') }
	]);
});

test('a review is saved and answered even when its alert cannot be redrawn', async (t) => {
	const f = await fixture(t);
	f.replies.editMessageReplyMarkup = () =>
		Response.json({ ok: false, error_code: 400, description: 'Bad Request: message not found' });
	const warn = t.mock.method(console, 'warn', () => undefined);
	await f.receive('fixture-token', callback());
	assert.equal((await f.archive.readReview(address))?.validated, true);
	assert.match(String(f.sent('answerCallbackQuery').at(-1)?.text), /Confirmed.*Saved/);
	assert.equal(warn.mock.callCount(), 1);
});

test('unconnected chats, another bot and bot users cannot review local recordings', async (t) => {
	const f = await fixture(t);
	await f.receive('fixture-token', callback(10, 'approved', 999));
	assert.match(String(f.calls.at(-1)?.body.text), /not connected/);
	await f.receive('different-token', callback());
	const bot = callback();
	bot.callback_query!.from.is_bot = true;
	await f.receive('fixture-token', bot);
	assert.equal(await f.archive.readReview(address), null);
	assert.deepEqual(f.sent('editMessageReplyMarkup'), []);
});

test('missing recordings and unrelated callbacks never claim a successful saved review', async (t) => {
	const f = await fixture(t);
	const missing = callback();
	missing.callback_query!.data = `review:${'b'.repeat(32)}:approved`;
	await f.receive('fixture-token', missing);
	assert.match(String(f.calls.at(-1)?.body.text), /no longer available/);
	assert.deepEqual(f.sent('editMessageReplyMarkup'), []);
	const count = f.calls.length;
	const unrelated = callback();
	unrelated.callback_query!.data = 'pairing-secret';
	await f.receive('fixture-token', unrelated);
	assert.equal(f.calls.length, count);
	assert.equal(await f.archive.readReview(address), null);
});

test('pairing and reviews consume one batch together, including callbacks after confirmation', async (t) => {
	const f = await fixture(t);
	const pairings = new TelegramPairings(Date.now, f.inbox);
	const pairing = await pairings.begin('fixture-token', 'private');
	t.after(() => pairings.cancel(pairing.id));
	const code = new URL(pairing.url).searchParams.get('start')!;
	f.replies.getUpdates = () => [start(1, code), callback(2)];
	assert.equal((await pairings.poll(pairing.id)).state, 'confirming');
	assert.equal((await f.archive.readReview(address))?.validated, true);
	f.replies.getUpdates = () => [confirmation(3, code), callback(4, 'rejected')];
	assert.equal((await pairings.poll(pairing.id)).state, 'matched');
	assert.equal((await f.archive.readReview(address))?.validated, false);
	f.replies.getUpdates = () => [];
	await pairings.receiveReviews('fixture-token', new AbortController().signal);
	assert.equal(f.sent('getUpdates').at(-1)?.offset, 5);
});

test('a failed archive write reports failure in Telegram and leaves the update available for retry', async (t) => {
	const f = await fixture(t);
	f.replies.getUpdates = () => [callback()];
	t.mock.method(f.archive, 'reviewEvent', async () => {
		throw new Error('Read-only archive');
	});
	await assert.rejects(f.inbox.receive('fixture-token'), /Read-only archive/);
	assert.match(String(f.calls.at(-1)?.body.text), /Could not save/);
	assert.equal(await f.archive.readReview(address), null);
	await assert.rejects(f.inbox.receive('fixture-token'), /Read-only archive/);
	assert.equal(f.sent('getUpdates').at(-1)?.offset, undefined);
});

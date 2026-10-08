import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test, type TestContext } from 'node:test';
import { DetectionArchive } from '../src/lib/server/archive.ts';
import { TelegramInbox } from '../src/lib/server/telegram-inbox.ts';
import { TelegramPairings } from '../src/lib/server/telegram-pairing.ts';
import { reviewTelegramDetection } from '../src/lib/server/telegram-reviews.ts';
import type { TelegramUpdate } from '../src/lib/server/telegram.ts';

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
	const directory = await mkdtemp(path.join(tmpdir(), 'ai-telegram-review-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	const root = path.join(directory, 'detections');
	const folder = path.join(root, address.type, address.archiveStage, address.timestamp);
	await mkdir(folder, { recursive: true });
	await writeFile(
		path.join(folder, 'metadata.json'),
		JSON.stringify({
			timestamp: address.timestamp,
			event_id: eventId,
			validated: null,
			confidence: 0.9,
			confidences: { activity: 0.9 },
			detections: 1,
			start: '2026-09-30T10:00:00',
			end: '2026-09-30T10:00:02',
			duration: 2
		})
	);
	const archive = new DetectionArchive(root);
	const calls: { method: string; body: Record<string, unknown> }[] = [];
	let updates: TelegramUpdate[] = [];
	t.mock.method(globalThis, 'fetch', async (url: string, init: RequestInit) => {
		assert.equal(new URL(url).origin, 'https://api.telegram.org');
		const method = new URL(url).pathname.split('/').at(-1)!;
		const body = JSON.parse(String(init.body));
		calls.push({ method, body });
		const replies: Record<string, unknown> = {
			getUpdates: updates,
			answerCallbackQuery: true,
			editMessageReplyMarkup: true,
			getMe: { is_bot: true, first_name: 'Alerts', username: 'FixtureBot' },
			getWebhookInfo: { url: '' },
			sendMessage: { message_id: 50 }
		};
		assert.ok(method in replies, method);
		return Response.json({ ok: true, result: replies[method] });
	});
	const receive = (token: string, update: TelegramUpdate, signal?: AbortSignal) =>
		reviewTelegramDetection(archive, connections, token, update, signal);
	return {
		archive,
		calls,
		receive,
		sent: (method: string) =>
			calls.filter((call) => call.method === method).map((call) => call.body),
		inbox: new TelegramInbox(receive),
		setUpdates(value: TelegramUpdate[]) {
			updates = value;
		}
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
	const transport = globalThis.fetch;
	t.mock.method(globalThis, 'fetch', async (url: string, init: RequestInit) =>
		String(url).endsWith('/editMessageReplyMarkup')
			? Response.json({ ok: false, error_code: 400, description: 'Bad Request: message not found' })
			: transport(url, init)
	);
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
	const pairing = await pairings.begin('fixture-token');
	t.after(() => pairings.cancel(pairing.id));
	const code = new URL(pairing.url).searchParams.get('start')!;
	f.setUpdates([
		{
			update_id: 1,
			message: {
				from: { id: 123, is_bot: false },
				chat: { id: 123, type: 'private' },
				text: `/start ${code}`
			}
		},
		callback(2)
	]);
	assert.equal((await pairings.poll(pairing.id)).state, 'confirming');
	assert.equal((await f.archive.readReview(address))?.validated, true);
	f.setUpdates([
		{
			update_id: 3,
			callback_query: {
				id: 'confirm',
				data: code,
				from: { id: 123, is_bot: false },
				message: { message_id: 50, chat: { id: 123, type: 'private' } }
			}
		},
		callback(4, 'rejected')
	]);
	assert.equal((await pairings.poll(pairing.id)).state, 'matched');
	assert.equal((await f.archive.readReview(address))?.validated, false);
	f.setUpdates([]);
	await pairings.receiveReviews('fixture-token', new AbortController().signal);
	assert.equal(f.calls.filter((call) => call.method === 'getUpdates').at(-1)?.body.offset, 5);
});

test('background polling yields to pairing and cached chats remain discoverable', async (t) => {
	const f = await fixture(t);
	const pairings = new TelegramPairings(Date.now, f.inbox);
	f.setUpdates([
		{
			update_id: 1,
			message: { chat: { id: 123, type: 'private', first_name: 'Farmer' }, text: 'hello' }
		}
	]);
	await pairings.receiveReviews('fixture-token', new AbortController().signal);
	f.setUpdates([]);
	assert.deepEqual(await pairings.discoverChats('fixture-token'), [{ id: '123', name: 'Farmer' }]);
	const pairing = await pairings.begin('fixture-token');
	t.after(() => pairings.cancel(pairing.id));
	const count = f.calls.length;
	await pairings.receiveReviews('fixture-token', new AbortController().signal);
	assert.equal(f.calls.length, count);
});

test('starting setup waits for an existing background poll instead of competing with it', async (t) => {
	const f = await fixture(t);
	const pairings = new TelegramPairings(Date.now, f.inbox);
	const entered = Promise.withResolvers<void>();
	const release = Promise.withResolvers<void>();
	const transport = globalThis.fetch;
	let polling = false;
	t.mock.method(globalThis, 'fetch', async (url: string, init: RequestInit) => {
		if (String(url).endsWith('/getUpdates')) {
			assert.equal(polling, false);
			polling = true;
			entered.resolve();
			await release.promise;
			polling = false;
		} else assert.equal(polling, false, 'Pairing begins after the background poll settles');
		return transport(url, init);
	});
	const background = pairings.receiveReviews('fixture-token', new AbortController().signal);
	await entered.promise;
	const starting = pairings.begin('fixture-token');
	await assert.rejects(pairings.begin('fixture-token'), /connection in progress/);
	release.resolve();
	const pairing = await starting;
	t.after(() => pairings.cancel(pairing.id));
	await background;
});

test('a failed archive write reports failure in Telegram and leaves the update available for retry', async (t) => {
	const f = await fixture(t);
	f.setUpdates([callback()]);
	t.mock.method(f.archive, 'reviewEvent', async () => {
		throw new Error('Read-only archive');
	});
	await assert.rejects(f.inbox.receive('fixture-token'), /Read-only archive/);
	assert.match(String(f.calls.at(-1)?.body.text), /Could not save/);
	assert.equal(await f.archive.readReview(address), null);
	await assert.rejects(f.inbox.receive('fixture-token'), /Read-only archive/);
	assert.equal(
		f.calls.filter((call) => call.method === 'getUpdates').at(-1)?.body.offset,
		undefined
	);
});

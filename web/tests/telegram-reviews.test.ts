import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
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

function callback(update_id = 10, stage = 'approved', chat = 123): TelegramUpdate {
	return {
		update_id,
		callback_query: {
			id: 'callback-' + update_id,
			data: `review:${eventId}:${stage}`,
			from: { id: 123, is_bot: false },
			message: { message_id: 42, chat: { id: chat, type: chat > 0 ? 'private' : 'channel' } }
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
			getMe: { is_bot: true, first_name: 'Alerts', username: 'FixtureBot' },
			getWebhookInfo: { url: '' },
			sendMessage: { message_id: 50 }
		};
		assert.ok(method in replies, method);
		return Response.json({ ok: true, result: replies[method] });
	});
	const offsets = path.join(directory, 'offsets');
	const receive = (token: string, update: TelegramUpdate, signal?: AbortSignal) =>
		reviewTelegramDetection(archive, connections, token, update, signal);
	return {
		directory,
		archive,
		calls,
		offsets,
		receive,
		inbox: new TelegramInbox(offsets, receive),
		setUpdates(value: TelegramUpdate[]) {
			updates = value;
		}
	};
}

test('private and channel callbacks from the same bot override each other and the web reads the result', async (t) => {
	const f = await fixture(t);
	await f.receive('fixture-token', callback());
	assert.equal((await f.archive.readReview(address))?.validated, true);
	assert.match(String(f.calls.at(-1)?.body.text), /Confirmed.*Saved/);
	await f.receive('fixture-token', callback(11, 'rejected', -456));
	const recording = (await f.archive.page({ offset: 0, limit: 24 })).items[0];
	assert.equal(recording.stage, 'rejected');
	assert.equal(recording.validated, null);
	assert.equal(recording.review?.source, 'telegram');
	assert.match(String(f.calls.at(-1)?.body.text), /false alarm.*Saved/);
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
});

test('missing recordings and unrelated callbacks never claim a successful saved review', async (t) => {
	const f = await fixture(t);
	const missing = callback();
	missing.callback_query!.data = `review:${'b'.repeat(32)}:approved`;
	await f.receive('fixture-token', missing);
	assert.match(String(f.calls.at(-1)?.body.text), /no longer available/);
	const count = f.calls.length;
	const unrelated = callback();
	unrelated.callback_query!.data = 'pairing-secret';
	await f.receive('fixture-token', unrelated);
	assert.equal(f.calls.length, count);
	assert.equal(await f.archive.readReview(address), null);
});

test('persisted offsets prevent old Telegram clicks from overwriting a later web review after restart', async (t) => {
	const f = await fixture(t);
	f.setUpdates([callback()]);
	await f.inbox.receive('fixture-token');
	await f.archive.review(address, false, 'web');
	const restarted = new TelegramInbox(f.offsets, f.receive);
	await restarted.receive('fixture-token');
	assert.equal(f.calls.filter((call) => call.method === 'getUpdates').at(-1)?.body.offset, 11);
	assert.equal((await f.archive.readReview(address))?.source, 'web');
	const [file] = await readdir(f.offsets);
	assert.doesNotMatch(file, /fixture-token/);
	assert.equal(await readFile(path.join(f.offsets, file), 'utf8'), '11\n');
	f.setUpdates([callback(12)]);
	await restarted.receive('fixture-token');
	assert.equal((await f.archive.readReview(address))?.validated, true);
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
	await assert.rejects(readdir(f.offsets), { code: 'ENOENT' });
});

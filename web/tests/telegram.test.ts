import assert from 'node:assert/strict';
import { test } from 'node:test';
import { sendTelegramNotice, sendTelegramTest } from '../src/lib/server/telegram.ts';
import { TelegramInbox } from '../src/lib/server/telegram-inbox.ts';

test('chat discovery returns unique recipient names without exposing message bodies', async (t) => {
	t.mock.method(
		globalThis,
		'fetch',
		async () =>
			new Response(
				JSON.stringify({
					ok: true,
					result: [
						{
							update_id: 0,
							message: {
								chat: { id: 1, type: 'private', first_name: 'Farmer' },
								text: 'private text'
							}
						},
						{ update_id: 1, message: { chat: { id: 1, type: 'private', first_name: 'Farmer' } } },
						{ update_id: 2, my_chat_member: { chat: { id: -2, type: 'group', title: 'Farm' } } },
						{ update_id: 3 }
					]
				})
			)
	);
	const inbox = new TelegramInbox();
	await inbox.receive('fixture-token');
	assert.deepEqual(inbox.chats('fixture-token'), [
		{ id: '1', name: 'Farmer' },
		{ id: '-2', name: 'Farm' }
	]);
});

test('a test alert is clearly labelled and Telegram rejection reaches the caller', async (t) => {
	let body = '';
	t.mock.method(globalThis, 'fetch', async (_url: string, init: RequestInit) => {
		body = String(init.body);
		return new Response(JSON.stringify({ ok: false, description: 'Chat not found' }));
	});
	await assert.rejects(sendTelegramTest('fixture-token', 'fixture-chat'), /Chat not found/);
	assert.match(body, /setup test/);
	assert.match(body, /confirm receipt/);
});

test('a notice of the application goes to its chat, without sound when asked, and a refusal reaches the caller', async (t) => {
	const bodies: Record<string, unknown>[] = [];
	let accepted = true;
	t.mock.method(globalThis, 'fetch', async (url: string, init: RequestInit) => {
		assert.match(String(url), /\/botfixture-token\/sendMessage$/);
		bodies.push(JSON.parse(String(init.body)));
		return new Response(JSON.stringify({ ok: accepted, description: 'Chat not found' }));
	});
	await sendTelegramNotice('fixture-token', 'fixture-chat', 'Not watched: Barn.', true);
	await sendTelegramNotice('fixture-token', 'fixture-chat', 'Watched again: Barn.', false);
	assert.deepEqual(bodies, [
		{ chat_id: 'fixture-chat', text: 'Not watched: Barn.', disable_notification: true },
		{ chat_id: 'fixture-chat', text: 'Watched again: Barn.', disable_notification: false }
	]);
	accepted = false;
	await assert.rejects(
		sendTelegramNotice('fixture-token', 'fixture-chat', 'Not watched: Barn.', false),
		/Chat not found/
	);
});

test('unavailable Telegram gives internet guidance without exposing request credentials', async (t) => {
	for (const failure of [
		new TypeError('fetch failed for https://api.telegram.org/botsecret-token/getUpdates'),
		new DOMException('The operation was aborted due to timeout', 'TimeoutError')
	]) {
		t.mock.method(globalThis, 'fetch', async () => {
			throw failure;
		});
		await assert.rejects(new TelegramInbox().receive('secret-token'), (error: Error) => {
			assert.match(error.message, /internet connection/);
			assert.match(error.message, /Local monitoring can continue/);
			assert.doesNotMatch(error.message, /secret-token/);
			return true;
		});
		t.mock.restoreAll();
	}
});

test('an invalid Telegram response offers retry instead of a JSON or schema error', async (t) => {
	for (const body of ['<h1>Service unavailable</h1>', '{"unexpected":true}']) {
		t.mock.method(globalThis, 'fetch', async () => new Response(body));
		await assert.rejects(
			new TelegramInbox().receive('fixture-token'),
			/unexpected reply.*try again later/
		);
		t.mock.restoreAll();
	}
});

test('the Telegram request deadline aborts the fetch and gives connection guidance', async (t) => {
	t.mock.timers.enable({ apis: ['setTimeout'] });
	let signal: AbortSignal | undefined;
	t.mock.method(globalThis, 'fetch', (_input: string, init: RequestInit) => {
		signal = init.signal!;
		return new Promise((_resolve, reject) => {
			signal!.addEventListener('abort', () => reject(signal!.reason), { once: true });
		});
	});
	const request = assert.rejects(
		new TelegramInbox().receive('fixture-token'),
		/internet connection/
	);
	assert.ok(signal);
	t.mock.timers.tick(10000);
	await request;
	assert.equal(signal.aborted, true);
});

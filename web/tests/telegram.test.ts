import assert from 'node:assert/strict';
import { test } from 'node:test';
import { findTelegramChats, sendTelegramTest } from '../src/lib/server/telegram.ts';

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
	assert.deepEqual(await findTelegramChats('fixture-token'), [
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

test('unavailable Telegram gives internet guidance without exposing request credentials', async (t) => {
	for (const failure of [
		new TypeError('fetch failed for https://api.telegram.org/botsecret-token/getUpdates'),
		new DOMException('The operation was aborted due to timeout', 'TimeoutError')
	]) {
		t.mock.method(globalThis, 'fetch', async () => {
			throw failure;
		});
		await assert.rejects(findTelegramChats('secret-token'), (error: Error) => {
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
		await assert.rejects(findTelegramChats('fixture-token'), /unexpected reply.*try again later/);
		t.mock.restoreAll();
	}
});

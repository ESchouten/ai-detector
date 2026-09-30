import assert from 'node:assert/strict';
import { test } from 'node:test';
import { BotCreationSessions } from '../telegram-manager/service.ts';

test('bot creation hands credentials only to its originating installation', async () => {
	let now = 1000;
	const sessions = new BotCreationSessions('manager_bot', () => now);
	const first = sessions.begin();
	const second = sessions.begin();
	const code = new URL(first.url).searchParams.get('start')!;
	assert.notEqual(first.id, code);
	assert.doesNotMatch(first.url, new RegExp(first.id));
	const sent: unknown[] = [];
	const sendMessage = async (...args: unknown[]) => {
		sent.push(args);
		return {} as never;
	};
	let username = '';
	await sessions.start(code, 123, {
		sendMessage: async (...args) => {
			username = (
				args[2]?.reply_markup as {
					keyboard: { request_managed_bot: { suggested_username: string } }[][];
				}
			).keyboard[0][0].request_managed_bot.suggested_username;
			return sendMessage(...args);
		}
	});
	assert.match(username, /^ai_detector_[a-f0-9]{12}_bot$/);
	await sessions.start(code, 999, { sendMessage });
	assert.equal(sent.length, 1, 'Another Telegram user cannot claim a started session');
	const tokens: number[] = [];
	const api = {
		sendMessage,
		getManagedBotToken: async (id: number) => {
			tokens.push(id);
			return 'fixture-new-bot-token';
		}
	};
	await sessions.created(999, { id: 10, username }, api);
	await sessions.created(123, { id: 11, username: 'another_bot' }, api);
	assert.deepEqual(tokens, []);
	assert.deepEqual(sessions.poll(first.id), { state: 'waiting' });
	await sessions.created(123, { id: 10, username }, api);
	assert.deepEqual(tokens, [10]);
	assert.deepEqual(sessions.poll(first.id), { state: 'created', token: 'fixture-new-bot-token' });
	assert.deepEqual(sessions.poll(second.id), { state: 'waiting' });
	await sessions.created(123, { id: 10, username }, api);
	assert.deepEqual(tokens, [10], 'Duplicate webhook cannot replace the handoff');
	sessions.cancel(first.id);
	assert.throws(() => sessions.poll(first.id), /expired/);
	now += 600001;
	assert.throws(() => sessions.poll(second.id), /expired/);
});

test('cancelled or expired sessions cannot publish late credentials', async () => {
	for (const expired of [false, true]) {
		let now = 0;
		const sessions = new BotCreationSessions('manager_bot', () => now);
		const session = sessions.begin();
		let username = '';
		await sessions.start(new URL(session.url).searchParams.get('start')!, 123, {
			sendMessage: async (_id, _text, options) => {
				username = (
					options!.reply_markup as {
						keyboard: { request_managed_bot: { suggested_username: string } }[][];
					}
				).keyboard[0][0].request_managed_bot.suggested_username;
				return {} as never;
			}
		});
		const deferred = Promise.withResolvers<string>();
		const creating = sessions.created(
			123,
			{ id: 10, username },
			{
				getManagedBotToken: () => deferred.promise,
				sendMessage: async () => {
					assert.fail('Abandoned creation must not finish');
				}
			}
		);
		if (expired) now = 600001;
		else sessions.cancel(session.id);
		deferred.resolve('fixture-token');
		await creating;
		assert.throws(() => sessions.poll(session.id), /expired/);
	}
});

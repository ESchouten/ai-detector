import assert from 'node:assert/strict';
import { test, type TestContext } from 'node:test';
import { ConfigurationError } from '../src/lib/configuration.ts';
import { TelegramPairings } from '../src/lib/server/telegram-pairing.ts';

type Request = { method: string; body: Record<string, unknown>; signal: AbortSignal };
type Reply = (request: Request) => unknown | Promise<unknown>;

function fixture(t: TestContext) {
	const calls: Request[] = [];
	const replies: Record<string, Reply> = {
		getMe: () => ({ is_bot: true, first_name: 'Farm alerts', username: 'FarmAlertsBot' }),
		getWebhookInfo: () => ({ url: '' }),
		getUpdates: () => []
	};
	t.mock.method(globalThis, 'fetch', async (input: string, init: RequestInit) => {
		const method = new URL(input).pathname.split('/').at(-1)!;
		assert.equal(new URL(input).origin, 'https://api.telegram.org');
		assert.equal(init.method, 'POST');
		assert.ok(init.signal instanceof AbortSignal);
		const request = { method, body: JSON.parse(String(init.body)), signal: init.signal };
		calls.push(request);
		assert.ok(replies[method], `Unexpected Telegram method: ${method}`);
		const result = await replies[method](request);
		return result instanceof Response ? result : Response.json({ ok: true, result });
	});
	let now = 1_800_000_000_000;
	const pairings = new TelegramPairings(() => now);
	const ids: string[] = [];
	t.after(async () => {
		for (const id of ids) await pairings.cancel(id);
	});
	return {
		calls,
		replies,
		pairings,
		advance(milliseconds: number) {
			now += milliseconds;
		},
		async begin(token = 'fixture-token') {
			const pairing = await pairings.begin(token);
			ids.push(pairing.id);
			return pairing;
		}
	};
}

function start(update: number, code: string, chat = 123) {
	return {
		update_id: update,
		message: {
			text: `/start ${code}`,
			from: { id: chat, is_bot: false },
			chat: { id: chat, type: 'private', first_name: 'Farmer', last_name: 'One' }
		}
	};
}

test('begin validates bot and webhook, returns a private QR link with a separate secret session ID', async (t) => {
	const f = fixture(t);
	const pairing = await f.begin();
	assert.deepEqual(pairing.bot, { name: 'Farm alerts', username: 'FarmAlertsBot' });
	const url = new URL(pairing.url);
	assert.equal(url.origin, 'https://t.me');
	assert.equal(url.pathname, '/FarmAlertsBot');
	const code = url.searchParams.get('start')!;
	assert.match(code, /^[A-Za-z0-9_-]{32}$/);
	assert.match(pairing.id, /^[A-Za-z0-9_-]{43}$/);
	assert.notEqual(pairing.id, code);
	assert.doesNotMatch(JSON.stringify(pairing), /fixture-token/);
	assert.equal(pairing.expiresAt, 1_800_000_000_000 + 5 * 60 * 1000);
	assert.match(pairing.qrDataUrl, /^data:image\/png;base64,/);
	const png = Buffer.from(pairing.qrDataUrl.split(',')[1], 'base64');
	assert.equal(png.subarray(1, 4).toString(), 'PNG');
	assert.equal(png.readUInt32BE(16), 256);
	assert.deepEqual(
		f.calls.map((call) => call.method),
		['getMe', 'getWebhookInfo']
	);
	await f.pairings.cancel(code);
	assert.deepEqual(await f.pairings.poll(pairing.id), { state: 'waiting' });
});

for (const error_code of [401, 404]) {
	test(`invalid token (${error_code}) has actionable feedback and releases its reservation`, async (t) => {
		const f = fixture(t);
		const valid = f.replies.getMe;
		f.replies.getMe = () => Response.json({ ok: false, error_code, description: 'Unauthorized' });
		await assert.rejects(f.begin(), /token is not valid.*BotFather/);
		assert.deepEqual(
			f.calls.map((call) => call.method),
			['getMe']
		);
		f.replies.getMe = valid;
		await f.begin();
	});
}

test('an existing webhook is refused without deleting it or receiving updates', async (t) => {
	const f = fixture(t);
	f.replies.getWebhookInfo = () => ({ url: 'https://another.example/hook' });
	await assert.rejects(f.begin(), /webhook.*has not been changed.*manually/);
	assert.deepEqual(
		f.calls.map((call) => call.method),
		['getMe', 'getWebhookInfo']
	);
	f.replies.getWebhookInfo = () => ({ url: '' });
	await f.begin();
});

test('only the exact private user start message matches, with bounded polling and advancing offsets', async (t) => {
	const f = fixture(t);
	const pairing = await f.begin();
	const code = new URL(pairing.url).searchParams.get('start')!;
	const group = start(1, code);
	group.message.chat.type = 'group';
	const extraText = start(3, `${code} extra`);
	const bot = start(4, code);
	bot.message.from.is_bot = true;
	const differentSender = start(5, code);
	differentSender.message.from.id = 999;
	const mention = start(6, code);
	mention.message.text = `/start@FarmAlertsBot ${code}`;
	f.replies.getUpdates = () => [
		group,
		start(2, 'unrelated-code'),
		extraText,
		bot,
		differentSender,
		mention,
		{ update_id: 7, callback_query: { data: code } }
	];
	assert.deepEqual(await f.pairings.poll(pairing.id), { state: 'waiting' });
	f.replies.getUpdates = () => [start(8, code)];
	const expected = { state: 'matched', chat: { id: '123', name: 'Farmer One' } };
	assert.deepEqual(await f.pairings.poll(pairing.id), expected);
	assert.deepEqual(
		f.calls.filter((call) => call.method === 'getUpdates').map((call) => call.body),
		[
			{ timeout: 3, limit: 100, allowed_updates: ['message', 'channel_post', 'my_chat_member'] },
			{
				timeout: 3,
				limit: 100,
				offset: 8,
				allowed_updates: ['message', 'channel_post', 'my_chat_member']
			}
		]
	);
	const requests = f.calls.length;
	f.replies.getUpdates = () => [start(9, code, 456)];
	assert.deepEqual(await f.pairings.poll(pairing.id), expected);
	assert.deepEqual(await f.pairings.poll(pairing.id), expected);
	assert.equal(f.calls.length, requests, 'Matched retries must not consume or rematch updates');
});

test('old and replayed link codes cannot match a new pairing for the same bot', async (t) => {
	const f = fixture(t);
	const old = await f.begin();
	const oldCode = new URL(old.url).searchParams.get('start')!;
	f.replies.getUpdates = () => [start(1, oldCode)];
	assert.equal((await f.pairings.poll(old.id)).state, 'matched');
	const current = await f.begin();
	const currentCode = new URL(current.url).searchParams.get('start')!;
	assert.notEqual(currentCode, oldCode);
	assert.deepEqual(await f.pairings.poll(current.id), { state: 'waiting' });
	f.replies.getUpdates = () => [start(2, currentCode, 456)];
	assert.deepEqual(await f.pairings.poll(current.id), {
		state: 'matched',
		chat: { id: '456', name: 'Farmer One' }
	});
	assert.deepEqual(await f.pairings.poll(old.id), {
		state: 'matched',
		chat: { id: '123', name: 'Farmer One' }
	});
});

test('expiry rejects old sessions, frees a token and never accepts an expired matching message', async (t) => {
	const f = fixture(t);
	const old = await f.begin();
	const code = new URL(old.url).searchParams.get('start')!;
	f.replies.getUpdates = () => [start(1, code)];
	f.advance(5 * 60 * 1000);
	await assert.rejects(f.pairings.poll(old.id), /expired/);
	assert.equal(f.calls.filter((call) => call.method === 'getUpdates').length, 0);
	await f.begin();
	await f.pairings.cancel(old.id);
});

test('concurrent begins reserve a token before identity lookup and manual discovery cannot compete', async (t) => {
	const f = fixture(t);
	const valid = f.replies.getMe;
	let release!: () => void;
	const gate = new Promise<void>((resolve) => {
		release = resolve;
	});
	f.replies.getMe = async (request) => {
		await gate;
		return valid(request);
	};
	const beginning = f.begin();
	await assert.rejects(f.begin(' fixture-token '), /connection in progress/);
	await assert.rejects(f.pairings.discoverChats('fixture-token'), /connection in progress/);
	assert.equal(f.calls.length, 1);
	release();
	await beginning;
});

test('concurrent polling shares one request and cancellation waits for its release', async (t) => {
	const f = fixture(t);
	const pairing = await f.begin();
	let receivedSignal!: AbortSignal;
	f.replies.getUpdates = ({ signal }) =>
		new Promise((_resolve, reject) => {
			receivedSignal = signal;
			signal.addEventListener('abort', () => reject(signal.reason), { once: true });
		});
	const first = f.pairings.poll(pairing.id);
	const second = f.pairings.poll(pairing.id);
	const firstRejected = assert.rejects(first, /cancelled/);
	const secondRejected = assert.rejects(second, /cancelled/);
	assert.equal(f.calls.filter((call) => call.method === 'getUpdates').length, 1);
	await f.pairings.cancel(pairing.id);
	await Promise.all([firstRejected, secondRejected]);
	assert.equal(receivedSignal.aborted, true);
	await assert.rejects(f.pairings.poll(pairing.id), /expired/);
	await f.pairings.cancel(pairing.id);
	await f.begin();
});

test('late replies after cancellation cannot match, and ownership stays reserved until they settle', async (t) => {
	const f = fixture(t);
	const pairing = await f.begin();
	const code = new URL(pairing.url).searchParams.get('start')!;
	let release!: () => void;
	const gate = new Promise<void>((resolve) => {
		release = resolve;
	});
	f.replies.getUpdates = async () => {
		await gate;
		return [start(1, code)];
	};
	const pending = assert.rejects(f.pairings.poll(pairing.id), /cancelled/);
	const cancelled = f.pairings.cancel(pairing.id);
	await assert.rejects(f.begin(), /connection in progress/);
	release();
	await Promise.all([pending, cancelled]);
	await f.begin();
});

test('begin expiry during network lookup cannot publish a live link or leak its token reservation', async (t) => {
	const f = fixture(t);
	const valid = f.replies.getMe;
	let release!: () => void;
	const gate = new Promise<void>((resolve) => {
		release = resolve;
	});
	f.replies.getMe = async (request) => {
		await gate;
		return valid(request);
	};
	const pending = assert.rejects(f.begin(), /expired/);
	f.advance(5 * 60 * 1000);
	await assert.rejects(f.begin(), /connection in progress/);
	release();
	await pending;
	f.replies.getMe = valid;
	await f.begin();
});

test('an expired in-flight match is rejected after its response arrives', async (t) => {
	const f = fixture(t);
	const pairing = await f.begin();
	const code = new URL(pairing.url).searchParams.get('start')!;
	f.replies.getUpdates = () => {
		f.advance(5 * 60 * 1000);
		return [start(1, code)];
	};
	await assert.rejects(f.pairings.poll(pairing.id), /expired/);
	await f.begin();
});

test('external polling conflict gives manual setup guidance and never changes the bot', async (t) => {
	const f = fixture(t);
	const pairing = await f.begin();
	f.replies.getUpdates = () =>
		Response.json({ ok: false, error_code: 409, description: 'Conflict' });
	await assert.rejects(f.pairings.poll(pairing.id), /another application.*chat ID manually/);
	assert.deepEqual(
		f.calls.map((call) => call.method),
		['getMe', 'getWebhookInfo', 'getUpdates']
	);
	await f.pairings.cancel(pairing.id);
	await f.begin();
});

test('manual discovery owns its update request and leaves the existing update filter unchanged', async (t) => {
	const f = fixture(t);
	let release!: () => void;
	const gate = new Promise<void>((resolve) => {
		release = resolve;
	});
	f.replies.getUpdates = async () => {
		await gate;
		return [start(1, 'hello')];
	};
	const discovery = f.pairings.discoverChats('fixture-token');
	await assert.rejects(f.begin(), /connection in progress/);
	await assert.rejects(f.pairings.discoverChats('fixture-token'), /connection in progress/);
	release();
	assert.deepEqual(await discovery, [{ id: '123', name: 'Farmer One' }]);
	assert.deepEqual(f.calls[0].body, { timeout: 3, limit: 100 });
	await f.begin();
});

test('malformed Telegram method results produce plain retry feedback, not schema internals', async (t) => {
	const f = fixture(t);
	const valid = f.replies.getMe;
	f.replies.getMe = () => ({ is_bot: true, first_name: 'Farm', username: '../bad?token=secret' });
	await assert.rejects(f.begin(), ConfigurationError);
	f.replies.getMe = valid;
	const pairing = await f.begin();
	for (const invalid of [null, {}, [{ update_id: 1, message: { chat: { id: 'invalid' } } }]]) {
		f.replies.getUpdates = () => invalid;
		await assert.rejects(f.pairings.poll(pairing.id), /unexpected reply.*try again later/);
	}
});

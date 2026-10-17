import assert from 'node:assert/strict';
import type { TestContext } from 'node:test';

type Request = { method: string; body: Record<string, unknown>; signal: AbortSignal };
type Reply = (request: Request) => unknown | Promise<unknown>;

/**
 * The Telegram Bot API in place of the network: each method answers from `replies`, and every
 * request is kept.
 */
export function telegramApi(t: TestContext) {
	const calls: Request[] = [];
	const replies: Record<string, Reply> = {
		getMe: () => ({ is_bot: true, first_name: 'Farm alerts', username: 'FarmAlertsBot' }),
		getWebhookInfo: () => ({ url: '' }),
		getUpdates: () => [],
		sendMessage: () => ({ message_id: 50 }),
		answerCallbackQuery: () => true,
		editMessageReplyMarkup: () => true
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
	return { calls, replies };
}

/** The message a pairing link sends when the farmer opens it. */
export function start(update: number, code: string, chat = 123) {
	return {
		update_id: update,
		message: {
			text: `/start ${code}`,
			from: { id: chat, is_bot: false },
			chat: { id: chat, type: 'private', first_name: 'Farmer', last_name: 'One' }
		}
	};
}

/** The press on the button under a pairing's test message. */
export function confirmation(update: number, code: string, user = 123, chat = 123, message = 50) {
	return {
		update_id: update,
		callback_query: {
			id: 'callback-' + update,
			data: code,
			from: { id: user, is_bot: false },
			message: { message_id: message, chat: { id: chat, type: chat > 0 ? 'private' : 'channel' } }
		}
	};
}

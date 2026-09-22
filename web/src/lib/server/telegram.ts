import * as v from 'valibot';
import { ConfigurationError } from '../configuration.ts';
import type { TelegramRecipient } from '../telegram.ts';

const responseSchema = v.object({
	ok: v.boolean(),
	description: v.optional(v.string()),
	error_code: v.optional(v.number()),
	result: v.optional(v.unknown())
});
const chatSchema = v.object({
	id: v.number(),
	type: v.string(),
	title: v.optional(v.string()),
	first_name: v.optional(v.string()),
	last_name: v.optional(v.string()),
	username: v.optional(v.string())
});
const messageSchema = v.object({
	chat: chatSchema,
	text: v.optional(v.string()),
	from: v.optional(v.object({ id: v.number(), is_bot: v.boolean() }))
});
const updatesSchema = v.array(
	v.object({
		update_id: v.pipe(v.number(), v.integer()),
		message: v.optional(messageSchema),
		channel_post: v.optional(messageSchema),
		my_chat_member: v.optional(v.object({ chat: chatSchema }))
	})
);

function result<T extends v.GenericSchema>(schema: T, value: unknown): v.InferOutput<T> {
	const parsed = v.safeParse(schema, value);
	if (!parsed.success)
		throw new ConfigurationError('Telegram returned an unexpected reply. Please try again later.');
	return parsed.output;
}

async function request(
	token: string,
	method: string,
	body: Record<string, unknown> = {},
	signal?: AbortSignal
) {
	let response: Response;
	try {
		response = await fetch(`https://api.telegram.org/bot${token}/${method}`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(body),
			signal: signal
				? AbortSignal.any([signal, AbortSignal.timeout(10000)])
				: AbortSignal.timeout(10000)
		});
	} catch (cause) {
		signal?.throwIfAborted();
		if (cause instanceof TypeError || (cause instanceof Error && cause.name === 'TimeoutError'))
			throw new ConfigurationError(
				'Telegram could not be reached. Check this computer’s internet connection, then try again. Local monitoring can continue without alerts.'
			);
		throw cause;
	}
	const payload = await response.json().catch(() => undefined);
	signal?.throwIfAborted();
	const reply = result(responseSchema, payload);
	if (reply.error_code === 401 || (method === 'getMe' && reply.error_code === 404))
		throw new ConfigurationError(
			'This bot token is not valid. Copy the current token from BotFather.'
		);
	if (reply.error_code === 409)
		throw new ConfigurationError(
			'This bot is receiving messages in another application or has a webhook. Use a dedicated bot for AI Detector, or enter its chat ID manually.'
		);
	if (!reply.ok)
		throw new ConfigurationError(
			reply.description ??
				'Telegram could not complete this request. Check your bot token and try again.'
		);
	return reply.result;
}

export async function getTelegramBot(token: string, signal?: AbortSignal) {
	const bot = result(
		v.object({
			is_bot: v.literal(true),
			first_name: v.string(),
			username: v.pipe(v.string(), v.regex(/^[A-Za-z0-9_]+$/))
		}),
		await request(token, 'getMe', {}, signal)
	);
	return { name: bot.first_name, username: bot.username };
}

export async function assertTelegramPollingAvailable(token: string, signal?: AbortSignal) {
	const webhook = result(
		v.object({ url: v.string() }),
		await request(token, 'getWebhookInfo', {}, signal)
	);
	if (webhook.url)
		throw new ConfigurationError(
			'This bot is connected to another application through a webhook. Its connection has not been changed. Use a dedicated bot for AI Detector, or enter its chat ID manually.'
		);
}

export async function getTelegramUpdates(
	token: string,
	options: { offset?: number; signal?: AbortSignal; allowedUpdates?: string[] } = {}
) {
	return result(
		updatesSchema,
		await request(
			token,
			'getUpdates',
			{
				timeout: 3,
				limit: 100,
				...(options.offset === undefined ? {} : { offset: options.offset }),
				...(options.allowedUpdates ? { allowed_updates: options.allowedUpdates } : {})
			},
			options.signal
		)
	);
}

export function telegramRecipient(chat: v.InferOutput<typeof chatSchema>): TelegramRecipient {
	return {
		id: String(chat.id),
		name:
			chat.title ??
			([chat.first_name, chat.last_name].filter(Boolean).join(' ') ||
				chat.username ||
				String(chat.id))
	};
}

export async function findTelegramChats(token: string) {
	const updates = await getTelegramUpdates(token);
	const chats = new Map<string, TelegramRecipient>();
	for (const update of updates) {
		const message = update.message ?? update.channel_post ?? update.my_chat_member;
		if (message) chats.set(String(message.chat.id), telegramRecipient(message.chat));
	}
	return [...chats.values()];
}

export async function sendTelegramTest(token: string, chat: string): Promise<void> {
	await request(token, 'sendMessage', {
		chat_id: chat,
		text: 'AI Detector setup test. If you received this message on the intended device, confirm receipt in AI Detector to enable alerts.'
	});
}

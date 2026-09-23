import { Api, GrammyError, HttpError } from 'grammy/web';
import type { Update } from 'grammy/types';
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

function api(token: string, signal?: AbortSignal): Api {
	const client = new Api(token, { fetch: globalThis.fetch, timeoutSeconds: 10 });
	// grammy/web uses native signals; its declarations still name the Node polyfill.
	const sdkSignal = signal as Parameters<Api['getMe']>[0];
	// The SDK supplies API types; validate external replies at the integration boundary.
	client.config.use(async (previous, method, payload) => {
		const reply = await previous(method, payload, sdkSignal);
		result(responseSchema, reply);
		return reply;
	});
	return client;
}

async function request<T>(operation: Promise<T>, signal?: AbortSignal): Promise<T> {
	try {
		const reply = await operation;
		signal?.throwIfAborted();
		return reply;
	} catch (cause) {
		signal?.throwIfAborted();
		if (cause instanceof GrammyError) throw apiError(cause);
		if (cause instanceof HttpError) {
			if (cause.error instanceof SyntaxError)
				throw new ConfigurationError(
					'Telegram returned an unexpected reply. Please try again later.'
				);
			throw new ConfigurationError(
				'Telegram could not be reached. Check this computer’s internet connection, then try again. Local monitoring can continue without alerts.'
			);
		}
		throw cause;
	}
}

function apiError(error: GrammyError): ConfigurationError {
	if (error.error_code === 401 || (error.method === 'getMe' && error.error_code === 404))
		return new ConfigurationError(
			'This bot token is not valid. Copy the current token from BotFather.'
		);
	if (error.error_code === 409)
		return new ConfigurationError(
			'This bot is receiving messages in another application or has a webhook. Use a dedicated bot for AI Detector, or enter its chat ID manually.'
		);
	return new ConfigurationError(
		error.description ??
			'Telegram could not complete this request. Check your bot token and try again.'
	);
}

export async function getTelegramBot(token: string, signal?: AbortSignal) {
	const bot = result(
		v.object({
			is_bot: v.literal(true),
			first_name: v.string(),
			username: v.pipe(v.string(), v.regex(/^[A-Za-z0-9_]+$/))
		}),
		await request(api(token, signal).getMe(), signal)
	);
	return { name: bot.first_name, username: bot.username };
}

export async function assertTelegramPollingAvailable(token: string, signal?: AbortSignal) {
	const webhook = result(
		v.object({ url: v.string() }),
		await request(api(token, signal).getWebhookInfo(), signal)
	);
	if (webhook.url)
		throw new ConfigurationError(
			'This bot is connected to another application through a webhook. Its connection has not been changed. Use a dedicated bot for AI Detector, or enter its chat ID manually.'
		);
}

export async function getTelegramUpdates(
	token: string,
	options: {
		offset?: number;
		signal?: AbortSignal;
		allowedUpdates?: Exclude<keyof Update, 'update_id'>[];
	} = {}
) {
	return result(
		updatesSchema,
		await request(
			api(token, options.signal).getUpdates({
				timeout: 3,
				limit: 100,
				offset: options.offset,
				allowed_updates: options.allowedUpdates
			}),
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
	await request(
		api(token).sendMessage(
			chat,
			'AI Detector setup test. If you received this message on the intended device, confirm receipt in AI Detector to enable alerts.'
		)
	);
}

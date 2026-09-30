import { randomBytes, randomInt } from 'node:crypto';
import QRCode from 'qrcode';
import { ConfigurationError } from '../configuration.ts';
import type {
	TelegramPairing,
	TelegramPairingState,
	TelegramRecipient,
	TelegramDestination
} from '../telegram.ts';
import {
	assertTelegramPollingAvailable,
	findTelegramChats,
	getTelegramBot,
	getTelegramUpdates,
	telegramRecipient,
	requestTelegramChat,
	sendTelegramConfirmation,
	acknowledgeTelegramConnection
} from './telegram.ts';

const LIFETIME_MS = 5 * 60 * 1000;
const MAX_SESSIONS = 16;
const EXPIRED = 'This Telegram connection link expired. Create a new link and open it in Telegram.';
const CANCELLED = 'This Telegram connection was cancelled. Create a new link to try again.';

interface Session {
	id: string;
	token: string;
	code: string;
	expiresAt: number;
	controller: AbortController;
	timer?: ReturnType<typeof setTimeout>;
	starting: boolean;
	offset?: number;
	chat?: TelegramRecipient;
	destination: TelegramDestination;
	requestId: number;
	user?: number;
	messageId?: number;
	confirmed: boolean;
	polling?: Promise<TelegramPairingState>;
}

type TelegramUpdate = Awaited<ReturnType<typeof getTelegramUpdates>>[number];

function privateMessage(update: TelegramUpdate) {
	const message = update.message;
	if (
		message?.chat.type !== 'private' ||
		!message.from ||
		message.from.is_bot ||
		message.from.id !== message.chat.id
	)
		return;
	return { ...message, from: message.from };
}

function confirmation(session: Session, update: TelegramUpdate) {
	const callback = update.callback_query;
	if (
		session.chat &&
		callback?.data === session.code &&
		callback.from.id === session.user &&
		!callback.from.is_bot &&
		String(callback.message?.chat.id) === session.chat.id &&
		callback.message?.message_id === session.messageId
	)
		return callback;
}

/** Temporary local pairing; a bot has only one update consumer in this process. */
export class TelegramPairings {
	private readonly sessions = new Map<string, Session>();
	private readonly discoveries = new Set<string>();
	private readonly now: () => number;

	constructor(now: () => number = Date.now) {
		this.now = now;
	}

	async begin(
		input: string,
		destination: TelegramDestination = 'private'
	): Promise<TelegramPairing> {
		const token = input.trim();
		this.expire();
		this.assertAvailable(token);
		if (this.sessions.size >= MAX_SESSIONS)
			throw new ConfigurationError(
				'Finish or cancel another Telegram connection before starting a new one.'
			);
		const session: Session = {
			id: randomBytes(32).toString('base64url'),
			token,
			code: randomBytes(24).toString('base64url'),
			expiresAt: this.now() + LIFETIME_MS,
			controller: new AbortController(),
			starting: true,
			destination,
			requestId: randomInt(1, 2147483647),
			confirmed: false
		};
		// Reserve the token before the first network wait, including concurrent starts.
		this.sessions.set(session.id, session);
		session.timer = setTimeout(() => this.end(session, EXPIRED), LIFETIME_MS);
		session.timer.unref();
		try {
			const bot = await getTelegramBot(token, session.controller.signal);
			await assertTelegramPollingAvailable(token, session.controller.signal);
			const url = `https://t.me/${bot.username}?start=${session.code}`;
			const qrDataUrl = await QRCode.toDataURL(url, { width: 256, margin: 4 });
			this.assertActive(session);
			return { id: session.id, bot, url, expiresAt: session.expiresAt, qrDataUrl };
		} catch (error) {
			this.end(session, CANCELLED);
			throw error;
		} finally {
			session.starting = false;
			if (session.controller.signal.aborted) this.sessions.delete(session.id);
		}
	}

	async poll(id: string): Promise<TelegramPairingState> {
		const session = this.sessions.get(id);
		if (!session) throw new ConfigurationError(EXPIRED);
		this.assertActive(session);
		if (session.confirmed) return this.state(session);
		session.polling ??= this.receive(session).finally(() => {
			session.polling = undefined;
			if (session.controller.signal.aborted) this.sessions.delete(session.id);
		});
		return session.polling;
	}

	async cancel(id: string): Promise<void> {
		const session = this.sessions.get(id);
		if (!session) return;
		this.end(session, CANCELLED);
		await session.polling?.catch(() => undefined);
	}

	async discoverChats(input: string): Promise<TelegramRecipient[]> {
		const token = input.trim();
		this.expire();
		this.assertAvailable(token);
		this.discoveries.add(token);
		try {
			return await findTelegramChats(token);
		} finally {
			this.discoveries.delete(token);
		}
	}

	private async receive(session: Session): Promise<TelegramPairingState> {
		const updates = await getTelegramUpdates(session.token, {
			offset: session.offset,
			signal: session.controller.signal,
			// Pairing is for a dedicated bot. Keep the manual discovery path's filter unchanged.
			allowedUpdates: ['message', 'channel_post', 'my_chat_member', 'callback_query']
		});
		this.assertActive(session);
		for (const update of updates) {
			session.offset = Math.max(session.offset ?? 0, update.update_id + 1);
			await this.receiveUpdate(session, update);
			this.assertActive(session);
			if (session.confirmed) break;
		}
		return this.state(session);
	}

	private async receiveUpdate(session: Session, update: TelegramUpdate): Promise<void> {
		const callback = confirmation(session, update);
		if (callback) {
			await acknowledgeTelegramConnection(session.token, callback.id, session.controller.signal);
			session.confirmed = true;
			return;
		}
		const message = privateMessage(update);
		if (!message) return;
		if (!session.user && message.text === `/start ${session.code}`) {
			session.user = message.from.id;
			if (session.destination === 'private')
				await this.confirm(session, telegramRecipient(message.chat));
			else
				await requestTelegramChat(
					session.token,
					session.user,
					session.destination,
					session.requestId,
					session.controller.signal
				);
			return;
		}
		const shared = message.chat_shared;
		if (
			!session.chat &&
			session.user === message.from.id &&
			shared?.request_id === session.requestId
		) {
			await this.confirm(session, {
				id: String(shared.chat_id),
				name: shared.title ?? 'My Telegram ' + session.destination
			});
		}
	}

	private state(session: Session): TelegramPairingState {
		if (session.chat)
			return { state: session.confirmed ? 'matched' : 'confirming', chat: session.chat };
		return { state: session.user ? 'choosing' : 'waiting' };
	}

	private async confirm(session: Session, chat: TelegramRecipient): Promise<void> {
		session.messageId = await sendTelegramConfirmation(
			session.token,
			chat.id,
			session.code,
			session.controller.signal
		);
		session.chat = chat;
	}

	private assertAvailable(token: string): void {
		if (
			this.discoveries.has(token) ||
			[...this.sessions.values()].some((session) => session.token === token && !session.confirmed)
		)
			throw new ConfigurationError(
				'This bot already has a connection in progress. Finish or cancel it before starting another.'
			);
	}

	private assertActive(session: Session): void {
		if (session.expiresAt <= this.now()) this.end(session, EXPIRED);
		session.controller.signal.throwIfAborted();
	}

	private expire(): void {
		for (const session of this.sessions.values()) {
			if (session.expiresAt <= this.now()) this.end(session, EXPIRED);
		}
	}

	private end(session: Session, message: string): void {
		clearTimeout(session.timer);
		session.controller.abort(new ConfigurationError(message));
		// An aborted request still owns the token until it has actually settled.
		if (!session.starting && !session.polling) this.sessions.delete(session.id);
	}
}

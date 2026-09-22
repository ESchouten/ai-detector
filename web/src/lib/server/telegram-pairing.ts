import { randomBytes } from 'node:crypto';
import QRCode from 'qrcode';
import { ConfigurationError } from '../configuration.ts';
import type { TelegramPairing, TelegramPairingState, TelegramRecipient } from '../telegram.ts';
import {
	assertTelegramPollingAvailable,
	findTelegramChats,
	getTelegramBot,
	getTelegramUpdates,
	telegramRecipient
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
	polling?: Promise<TelegramPairingState>;
}

/** Temporary local pairing; a bot has only one update consumer in this process. */
export class TelegramPairings {
	private readonly sessions = new Map<string, Session>();
	private readonly discoveries = new Set<string>();
	private readonly now: () => number;

	constructor(now: () => number = Date.now) {
		this.now = now;
	}

	async begin(input: string): Promise<TelegramPairing> {
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
			starting: true
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
		if (session.chat) return { state: 'matched', chat: session.chat };
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
			allowedUpdates: ['message', 'channel_post', 'my_chat_member']
		});
		this.assertActive(session);
		for (const update of updates) {
			session.offset = Math.max(session.offset ?? 0, update.update_id + 1);
			const message = update.message;
			if (
				message?.chat.type === 'private' &&
				message.from?.is_bot === false &&
				message.from.id === message.chat.id &&
				message.text === `/start ${session.code}`
			) {
				session.chat = telegramRecipient(message.chat);
				return { state: 'matched', chat: session.chat };
			}
		}
		return { state: 'waiting' };
	}

	private assertAvailable(token: string): void {
		if (
			this.discoveries.has(token) ||
			[...this.sessions.values()].some((session) => session.token === token && !session.chat)
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

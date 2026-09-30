import { randomBytes } from 'node:crypto';
import type { Api } from 'grammy';

const LIFETIME = 10 * 60 * 1000;
interface Session {
	id: string;
	code: string;
	username: string;
	expiresAt: number;
	user?: number;
	token?: string;
	timer?: ReturnType<typeof setTimeout>;
}

/** A temporary handoff between one installation and a bot's Telegram owner. */
export class BotCreationSessions {
	private sessions = new Map<string, Session>();
	private manager: string;
	private now: () => number;
	constructor(manager: string, now: () => number = Date.now) {
		this.manager = manager;
		this.now = now;
	}
	private expire() {
		for (const [id, session] of this.sessions) if (session.expiresAt <= this.now()) this.cancel(id);
	}
	begin() {
		this.expire();
		if (this.sessions.size >= 100)
			throw new Error('Bot creation is busy. Try again in a few minutes.');
		const id = randomBytes(32).toString('base64url');
		const code = randomBytes(24).toString('hex');
		const session: Session = {
			id,
			code,
			username: `ai_detector_${code.slice(0, 12)}_bot`,
			expiresAt: this.now() + LIFETIME
		};
		session.timer = setTimeout(() => this.cancel(id), LIFETIME);
		session.timer.unref();
		this.sessions.set(id, session);
		return { id, url: `https://t.me/${this.manager}?start=${code}`, expiresAt: session.expiresAt };
	}
	poll(id: string) {
		this.expire();
		const session = this.sessions.get(id);
		if (!session) throw new Error('The creation link expired. Start again.');
		return session.token
			? { state: 'created' as const, token: session.token }
			: { state: 'waiting' as const };
	}
	cancel(id: string) {
		clearTimeout(this.sessions.get(id)?.timer);
		this.sessions.delete(id);
	}
	async start(code: string, user: number, api: Pick<Api, 'sendMessage'>) {
		this.expire();
		const session = [...this.sessions.values()].find((item) => item.code === code);
		if (!session || session.token || (session.user !== undefined && session.user !== user)) return;
		session.user = user;
		await api.sendMessage(
			user,
			'Create your AI Detector bot below. Keep the suggested username so your computer can receive the connection. Then return to AI Detector.',
			{
				reply_markup: {
					keyboard: [
						[
							{
								text: 'Create my AI Detector bot',
								request_managed_bot: {
									request_id: 1,
									suggested_name: 'AI Detector alerts',
									suggested_username: session.username
								}
							}
						]
					],
					resize_keyboard: true,
					one_time_keyboard: true
				}
			}
		);
	}
	async created(
		user: number,
		bot: { id: number; username?: string },
		api: Pick<Api, 'getManagedBotToken' | 'sendMessage'>
	) {
		this.expire();
		const session = [...this.sessions.values()].find(
			(item) => item.user === user && item.username.toLowerCase() === bot.username?.toLowerCase()
		);
		if (!session || session.token) return;
		const token = await api.getManagedBotToken(bot.id);
		this.expire();
		if (!this.sessions.has(session.id)) return;
		session.token = token;
		await api.sendMessage(
			user,
			'Your bot is ready. Return to AI Detector to choose where to receive alerts.',
			{ reply_markup: { remove_keyboard: true } }
		);
	}
}

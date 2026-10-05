import { getTelegramUpdates, telegramChats, type TelegramUpdate } from './telegram.ts';
import type { TelegramRecipient } from '../telegram.ts';

type ReceiveUpdate = (token: string, update: TelegramUpdate, signal?: AbortSignal) => Promise<void>;

/** Pairing and background reviews share offsets; TelegramPairings owns exclusive polling. */
export class TelegramInbox {
	private offsets = new Map<string, number>();
	private recipients = new Map<string, Map<string, TelegramRecipient>>();
	private onUpdate?: ReceiveUpdate;

	constructor(onUpdate?: ReceiveUpdate) {
		this.onUpdate = onUpdate;
	}

	async receive(
		token: string,
		signal?: AbortSignal,
		consume?: (update: TelegramUpdate) => Promise<void>
	): Promise<void> {
		let offset = this.offsets.get(token);
		const updates = await getTelegramUpdates(token, {
			offset,
			signal,
			allowedUpdates: ['message', 'channel_post', 'my_chat_member', 'callback_query']
		});
		const chats = this.recipients.get(token) ?? new Map<string, TelegramRecipient>();
		for (const chat of telegramChats(updates)) chats.set(chat.id, chat);
		while (chats.size > 100) chats.delete(chats.keys().next().value!);
		this.recipients.set(token, chats);
		for (const update of updates) {
			if (offset !== undefined && update.update_id < offset) continue;
			await this.onUpdate?.(token, update, signal);
			await consume?.(update);
			offset = update.update_id + 1;
			this.offsets.set(token, offset);
		}
	}

	chats(token: string): TelegramRecipient[] {
		return [...(this.recipients.get(token)?.values() ?? [])];
	}
}

import { createHash } from 'node:crypto';
import path from 'node:path';
import { getTelegramUpdates, telegramChats, type TelegramUpdate } from './telegram.ts';
import type { TelegramRecipient } from '../telegram.ts';
import { readJson, writeJson } from './json-file.ts';

type ReceiveUpdate = (token: string, update: TelegramUpdate, signal?: AbortSignal) => Promise<void>;

/** Pairing and background reviews share offsets; TelegramPairings owns exclusive polling. */
export class TelegramInbox {
	private offsets = new Map<string, number>();
	private recipients = new Map<string, Map<string, TelegramRecipient>>();
	private directory?: string;
	private onUpdate?: ReceiveUpdate;

	constructor(directory?: string, onUpdate?: ReceiveUpdate) {
		this.directory = directory;
		this.onUpdate = onUpdate;
	}

	async receive(
		token: string,
		signal?: AbortSignal,
		consume?: (update: TelegramUpdate) => Promise<void>
	): Promise<void> {
		const file =
			this.directory &&
			path.join(this.directory, createHash('sha256').update(token).digest('hex') + '.json');
		let offset = this.offsets.get(token);
		if (offset === undefined && file) offset = (await readJson<number>(file)) ?? undefined;
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
			// Persist before the next getUpdates acknowledges it, including across app restarts.
			if (file) await writeJson(file, offset);
			this.offsets.set(token, offset);
		}
	}

	chats(token: string): TelegramRecipient[] {
		return [...(this.recipients.get(token)?.values() ?? [])];
	}
}

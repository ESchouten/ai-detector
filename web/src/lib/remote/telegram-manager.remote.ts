import { command, query } from '$app/server';
import * as v from 'valibot';
import { configurationAction } from '$lib/server/configuration/request';
import {
	beginBotCreation,
	pollBotCreation,
	cancelBotCreation,
	telegramManagerAvailable
} from '$lib/server/telegram-manager';

export const canCreateTelegramBot = query(telegramManagerAvailable);
export const createTelegramBot = command(() => configurationAction(beginBotCreation()));
export const pollTelegramBotCreation = command(v.string(), (id) =>
	configurationAction(pollBotCreation(id))
);
export const cancelTelegramBotCreation = command(v.string(), (id) =>
	configurationAction(cancelBotCreation(id))
);

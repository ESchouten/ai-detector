import type * as v from 'valibot';
import { ConfigurationError, sameTelegram, telegramInput } from '../../configuration.ts';
import type { Configuration } from '../../schema.ts';

export function saveTelegram(
	{ config, app }: Configuration,
	input: v.InferOutput<typeof telegramInput>
): void {
	const index = input.original
		? app.telegrams.findIndex((item) => item.label === input.original)
		: -1;
	if (input.original && index < 0)
		throw new ConfigurationError('This notification channel no longer exists.');
	if (
		app.telegrams.some(
			(item, i) => i !== index && (item.label === input.label || sameTelegram(item, input))
		)
	) {
		throw new ConfigurationError('This notification channel or name already exists.');
	}
	const previous = app.telegrams[index];
	const telegram = { label: input.label, token: input.token, chat: input.chat };
	if (index < 0) app.telegrams.push(telegram);
	else app.telegrams[index] = telegram;
	if (!previous) return;
	for (const detector of config.detectors) {
		for (const exporter of detector.exporters?.telegram ?? []) {
			if (sameTelegram(exporter, previous))
				Object.assign(exporter, { token: input.token, chat: input.chat });
		}
	}
}

export function deleteTelegram({ config, app }: Configuration, label: string): void {
	const telegram = app.telegrams.find((item) => item.label === label);
	if (!telegram) throw new ConfigurationError('This notification channel no longer exists.');
	app.telegrams = app.telegrams.filter((item) => item !== telegram);
	for (const detector of config.detectors) {
		if (detector.exporters?.telegram)
			detector.exporters.telegram = detector.exporters.telegram.filter(
				(item) => !sameTelegram(item, telegram)
			);
	}
}

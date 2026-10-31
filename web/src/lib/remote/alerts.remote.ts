import { configurationAction } from '$lib/server/configuration/request';
import { command, query } from '$app/server';
import * as v from 'valibot';
import QRCode from 'qrcode';
import { configuration } from '$lib/server/configuration';
import { newPhoneAlarmTopic, phoneAlarmLink } from '$lib/phone-alarm';
import { readPresetsForSaving } from '$lib/server/configuration/presets';
import { alertsInput, telegramInput } from '$lib/configuration';
import { telegramMeta } from '$lib/schema';
import { sendTelegramTest } from '$lib/server/telegram';
import { sendPhoneAlarmTest } from '$lib/server/ntfy';
import { phoneAlarmDetectors } from '$lib/server/configuration/phone-alarm';
import { telegramPairings as pairings } from '$lib/server/telegram-service';

const tokenInput = v.object({ token: v.pipe(v.string(), v.trim(), v.minLength(1)) });
const pairingInput = v.object({ id: v.pipe(v.string(), v.minLength(1)) });

export const beginTelegramPairing = command(
	v.object({
		...tokenInput.entries,
		destination: v.picklist(['private', 'group', 'channel'])
	}),
	({ token, destination }) => configurationAction(() => pairings.begin(token, destination))
);
export const pollTelegramPairing = command(pairingInput, ({ id }) =>
	configurationAction(() => pairings.poll(id))
);
export const cancelTelegramPairing = command(pairingInput, ({ id }) =>
	configurationAction(() => pairings.cancel(id))
);

export const saveAlerts = command(alertsInput, (input) =>
	configurationAction(async () => configuration.saveAlerts(input, await readPresetsForSaving()))
);
export const discoverTelegramChats = command(tokenInput, ({ token }) =>
	configurationAction(() => pairings.discoverChats(token))
);

export const getTelegrams = query(async () => (await configuration.read()).app.telegrams);

export const getOutageNotifications = query(
	async () => (await configuration.read()).app.notifyCameraOutages === true
);

export const saveOutageNotifications = command(v.boolean(), (enabled) =>
	configurationAction(() => configuration.saveOutageNotifications(enabled))
);

export const connectTelegram = command(telegramInput, (input) =>
	configurationAction(() => configuration.saveTelegram(input))
);

export const deleteTelegram = command(v.pick(telegramMeta, ['label']), ({ label }) =>
	configurationAction(() => configuration.deleteTelegram(label))
);

export const testTelegram = command(v.pick(telegramMeta, ['token', 'chat']), ({ token, chat }) =>
	configurationAction(() => sendTelegramTest(token, chat))
);

const phoneAlarmInput = v.object({
	topic: v.pipe(v.string(), v.regex(/^[-_A-Za-z0-9]{1,64}$/)),
	detectorLabels: v.array(v.string())
});

/** The saved alarm, or a new topic to set one up with. */
export const getPhoneAlarm = query(async () => {
	const document = await configuration.read();
	const saved = document.app.phoneAlarm?.topic;
	const topic = saved ?? newPhoneAlarmTopic();
	return {
		topic,
		saved: Boolean(saved),
		detectorLabels: phoneAlarmDetectors(document),
		link: phoneAlarmLink(topic),
		qr: await QRCode.toDataURL(phoneAlarmLink(topic), { margin: 1, width: 256 })
	};
});

export const savePhoneAlarm = command(phoneAlarmInput, (input) =>
	configurationAction(() => configuration.savePhoneAlarm(input))
);

export const deletePhoneAlarm = command(() =>
	configurationAction(() => configuration.deletePhoneAlarm())
);

export const testPhoneAlarm = command(v.pick(phoneAlarmInput, ['topic']), ({ topic }) =>
	configurationAction(() => sendPhoneAlarmTest(topic))
);

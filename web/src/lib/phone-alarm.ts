import type { WebhookConfig } from './generated/config.js';

/** The public ntfy server. Its phone apps deliver alarms without an account. */
export const NTFY_SERVER = 'https://ntfy.sh';
const TOPIC_ALPHABET = 'abcdefghijklmnopqrstuvwxyz0123456789';

/** Anyone who knows the topic can read and send its alarms, so it is long and random. */
export function newPhoneAlarmTopic(): string {
	const bytes = crypto.getRandomValues(new Uint8Array(20));
	return `aidetector-${Array.from(bytes, (byte) => TOPIC_ALPHABET[byte % TOPIC_ALPHABET.length]).join('')}`;
}

export function phoneAlarmUrl(topic: string): string {
	return `${NTFY_SERVER}/${topic}`;
}

/** Opens the ntfy Android app on the topic and subscribes to it. */
export function phoneAlarmLink(topic: string): string {
	return `ntfy://${new URL(NTFY_SERVER).host}/${topic}?display=AI%20Detector`;
}

/** A detector's alarm: the highest priority, which the phone may let ring through Do Not Disturb. */
export function phoneAlarmExporter(topic: string, detector: string): WebhookConfig {
	return {
		url: phoneAlarmUrl(topic),
		method: 'POST',
		headers: { Title: 'AI Detector', Priority: 'urgent', Tags: 'rotating_light' },
		body: detector,
		data_type: 'none'
	};
}

export function isPhoneAlarm(exporter: WebhookConfig, topic: string): boolean {
	return exporter.url === phoneAlarmUrl(topic);
}

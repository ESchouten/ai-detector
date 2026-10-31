import { ConfigurationError } from '../../configuration.ts';
import { isPhoneAlarm, phoneAlarmExporter } from '../../phone-alarm.ts';
import type { Configuration } from '../../schema.ts';

/** The detectors that ring the phone alarm, by name. */
export function phoneAlarmDetectors({ config, app }: Configuration): string[] {
	const topic = app.phoneAlarm?.topic;
	if (!topic) return [];
	return app.detectors
		.filter((_, index) =>
			config.detectors[index].exporters?.webhook?.some((item) => isPhoneAlarm(item, topic))
		)
		.map((meta) => meta.label);
}

function assign({ config, app }: Configuration, topic: string | undefined, selected: Set<string>) {
	const previous = app.phoneAlarm?.topic;
	for (const [index, detector] of config.detectors.entries()) {
		const label = app.detectors[index].label;
		const others = (detector.exporters?.webhook ?? []).filter(
			(item) => !previous || !isPhoneAlarm(item, previous)
		);
		const webhook =
			topic && selected.has(label) ? [...others, phoneAlarmExporter(topic, label)] : others;
		if (webhook.length || detector.exporters?.webhook) {
			detector.exporters ??= {};
			detector.exporters.webhook = webhook;
		}
	}
	if (topic) app.phoneAlarm = { topic };
	else delete app.phoneAlarm;
}

export function savePhoneAlarm(
	document: Configuration,
	{ topic, detectorLabels }: { topic: string; detectorLabels: string[] }
): void {
	const selected = new Set(detectorLabels);
	if ([...selected].some((label) => !document.app.detectors.some((meta) => meta.label === label)))
		throw new ConfigurationError('A selected detector no longer exists.');
	assign(document, topic, selected);
}

export function deletePhoneAlarm(document: Configuration): void {
	assign(document, undefined, new Set());
}

/** Alarms name their detector, so a renamed detector's alarm follows its new name. */
export function renamePhoneAlarms(document: Configuration): void {
	const topic = document.app.phoneAlarm?.topic;
	if (topic) assign(document, topic, new Set(phoneAlarmDetectors(document)));
}

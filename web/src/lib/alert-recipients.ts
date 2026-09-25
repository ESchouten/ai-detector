import { sameTelegram } from './configuration.ts';
import type { DetectorConfig, DetectorMeta, TelegramMeta } from './schema.ts';

export function recipientDetectorLabels(
	detectors: { detector: DetectorConfig; meta: DetectorMeta }[],
	recipient?: TelegramMeta,
	additionalDetector?: string
): string[] {
	return detectors
		.filter(
			({ detector, meta }) =>
				meta.label === additionalDetector ||
				(recipient &&
					detector.exporters?.telegram?.some((channel) => sameTelegram(channel, recipient)))
		)
		.map(({ meta }) => meta.label);
}

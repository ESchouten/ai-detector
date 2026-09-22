import { normalizeConfig, sameTelegram } from './configuration.ts';
import type { DetectorConfig, TelegramConfig, TelegramMeta } from './schema.ts';

export type DetectorDraft = DetectorConfig & {
	exporters: NonNullable<DetectorConfig['exporters']>;
};

export function createDetectorDraft(saved?: DetectorConfig): DetectorDraft {
	const detector = saved
		? structuredClone(saved)
		: {
				detection: { source: [] },
				yolo: { model: 'yolo11n.pt', confidence: 0.8 },
				exporters: { disk: [{}] }
			};
	return { ...detector, exporters: detector.exporters ?? {} };
}

export function parseDetectorDraft(text: string): DetectorDraft {
	const config = normalizeConfig({ detectors: [JSON.parse(text)] });
	return createDetectorDraft(config.detectors[0]);
}

/** Change the watched behavior without changing the camera or its delivery destinations. */
export function applyDetectorPreset(
	current: DetectorConfig,
	preset: DetectorConfig
): DetectorDraft {
	return createDetectorDraft({
		...structuredClone(preset),
		detection: { ...preset.detection, source: [...current.detection.source] },
		exporters: structuredClone(current.exporters ?? preset.exporters)
	});
}

export function selectTelegram(
	current: TelegramConfig[],
	channel: TelegramMeta,
	selected: boolean
): TelegramConfig[] {
	if (!selected) return current.filter((exporter) => !sameTelegram(exporter, channel));
	if (current.some((exporter) => sameTelegram(exporter, channel))) return current;
	return [...current, { token: channel.token, chat: channel.chat }];
}

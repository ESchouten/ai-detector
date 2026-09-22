import { normalizeConfig, sameTelegram } from './configuration.ts';
import type { DetectorConfig, PresetInfo, TelegramConfig, TelegramMeta } from './schema.ts';

export function cameraRuleNames(
	rules: { label: string; preset?: string }[],
	presets: PresetInfo[]
): string {
	return rules
		.map((rule) => presets.find((preset) => preset.id === rule.preset)?.name ?? rule.label)
		.join(', ');
}

export type DetectorDraft = DetectorConfig & {
	exporters: NonNullable<DetectorConfig['exporters']>;
};

export type CameraMonitoringChoice =
	| { mode: 'preset'; preset: string }
	| { mode: 'keep' }
	| { mode: 'view-only' }
	| { mode: 'copy' };

/** Preset IDs live in their own namespace so they cannot collide with camera actions. */
export function cameraMonitoringChoice(selection: string): CameraMonitoringChoice | undefined {
	if (selection === 'keep' || selection === 'view-only' || selection === 'copy')
		return { mode: selection };
	if (selection.startsWith('preset:') && selection.length > 'preset:'.length)
		return { mode: 'preset', preset: selection.slice('preset:'.length) };
	return undefined;
}

export function createDetectorDraft(saved?: DetectorConfig): DetectorDraft {
	const detector = saved
		? structuredClone(saved)
		: {
				detection: { source: [] },
				yolo: { model: '' },
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

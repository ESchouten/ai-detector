import { detectorSettings, normalizeConfig, sameTelegram } from './configuration.ts';
import { connectionMatches } from './llm.ts';
import type {
	DetectorConfig,
	DetectorMeta,
	LlmConnection,
	PresetInfo,
	TelegramConfig,
	TelegramMeta
} from './schema.ts';

export function detectorDraftMeta(
	detector: DetectorConfig,
	label: string,
	preset: { id: string; settings: string },
	connection?: LlmConnection
): DetectorMeta {
	const [verification] = detector.vlm ?? [];
	return {
		label,
		preset:
			preset.id && JSON.stringify(detectorSettings(detector)) === preset.settings
				? preset.id
				: undefined,
		llmConnection:
			connection && verification && connectionMatches(verification, connection)
				? connection.label
				: undefined
	};
}

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

/** Keep camera choices; existing detectors also keep their delivery destinations. */
export function applyDetectorPreset(
	current: DetectorConfig,
	preset: DetectorConfig,
	{ keepDelivery = true }: { keepDelivery?: boolean } = {}
): DetectorDraft {
	const next = createDetectorDraft({
		...structuredClone(preset),
		detection: { ...preset.detection, source: [...current.detection.source] },
		exporters: structuredClone(keepDelivery ? current.exporters : preset.exporters)
	});
	const previous = current.vlm?.[0];
	// Retain a paused connection's model choices so it does not become a waiting preset again.
	if (next.vlm?.[0] && previous?.key == null && previous?.model?.length) {
		next.vlm[0].model = structuredClone(previous.model);
		next.vlm[0].key = null;
	}
	return next;
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

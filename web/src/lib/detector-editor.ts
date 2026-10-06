import {
	detectorSettings,
	normalizeConfig,
	sameTelegram,
	telegramExporter,
	uniqueLabel
} from './configuration.ts';
import type { DetectorChoices } from './detector-draft-storage.ts';
import { assignConnection, connectionMatches, suggestedConnection } from './llm.ts';
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
	preset: { id: string; settings: string; autoUpdate: boolean },
	connection?: LlmConnection
): DetectorMeta {
	const [verification] = detector.vlm ?? [];
	const followed =
		preset.id && JSON.stringify(detectorSettings(detector)) === preset.settings
			? preset.id
			: undefined;
	return {
		label,
		preset: followed,
		autoUpdate: followed && !preset.autoUpdate ? false : undefined,
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

/** The draft as it will be saved: checked against the detector's schema, in its list form. */
export function validDetectorDraft(detector: unknown): DetectorDraft {
	return createDetectorDraft(normalizeConfig({ detectors: [detector] }).detectors[0]);
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
	return [...current, telegramExporter(channel)];
}

/** What the detector editor is working on: the rule, and the choices saved beside it. */
export interface DetectorEdit {
	label: string;
	/** The name a preset last suggested. A name the person typed is never replaced. */
	suggestedLabel: string;
	detector: DetectorDraft;
	preset: string;
	/** The settings the chosen preset gave, to tell whether the rule still follows it. */
	presetSettings: string;
	/** The saved AI connection in use, by name; empty for none. */
	connection: string;
}

/** What this installation offers the editor to choose from. */
export interface DetectorOptions {
	cameras: { id: string; source: string }[];
	telegrams: TelegramMeta[];
	connections: LlmConnection[];
	presets: PresetInfo[];
	/** Names already taken by other detectors. */
	usedLabels: string[];
}

/** Whether the rule still has the settings its preset gave it. */
export function followsPreset(detector: DetectorConfig, presetSettings: string): boolean {
	return JSON.stringify(detectorSettings(detector)) === presetSettings;
}

function followedPreset(edit: DetectorEdit, presets: PresetInfo[]): PresetInfo | undefined {
	return followsPreset(edit.detector, edit.presetSettings)
		? presets.find((item) => item.id === edit.preset)
		: undefined;
}

/**
 * The choices to keep in the browser while an edit is unfinished: references to saved settings
 * only, never camera addresses, bot tokens or connection keys.
 */
export function detectorChoices(
	edit: Pick<DetectorEdit, 'label' | 'preset' | 'detector' | 'connection'>,
	options: Pick<DetectorOptions, 'cameras' | 'telegrams'>
): DetectorChoices {
	const channels = edit.detector.exporters.telegram ?? [];
	return {
		label: edit.label,
		preset: edit.preset,
		cameras: options.cameras
			.filter((camera) => edit.detector.detection.source.includes(camera.source))
			.map((camera) => camera.id),
		telegrams: options.telegrams
			.filter((channel) => channels.some((item) => sameTelegram(item, channel)))
			.map((channel) => channel.label),
		connection: edit.connection,
		validatorEnabled: !!edit.detector.vlm?.some((verifier) => verifier.key)
	};
}

/** A connected rule has nothing to ask until a preset supplies its question. */
export function lacksQuestion(detector: DetectorConfig): boolean {
	return !detector.vlm?.[0]?.prompt.trim();
}

/** The connection for a preset's question: the one in use, or the only one there is if asked. */
function questionConnection(
	detector: DetectorConfig,
	inUse: string,
	connections: LlmConnection[],
	suggest: boolean
): LlmConnection | undefined {
	if (lacksQuestion(detector)) return undefined;
	return (
		connections.find(({ label }) => label === inUse) ??
		(suggest ? suggestedConnection(detector, connections) : undefined)
	);
}

/** A preset names the rule, unless the person typed a name of their own. */
function presetLabel(edit: DetectorEdit, id: string, options: DetectorOptions): string | undefined {
	const previousName = followedPreset(edit, options.presets)?.name;
	if (edit.label && edit.label !== previousName && edit.label !== edit.suggestedLabel) return;
	return uniqueLabel(
		options.presets.find((item) => item.id === id)?.name ?? edit.label,
		new Set(options.usedLabels)
	);
}

/**
 * The edit after choosing a preset: its detection settings, its name unless one was typed, and
 * a connection for its question when one is in use or may be suggested.
 */
export function choosePreset(
	edit: DetectorEdit,
	preset: { id: string; detector: DetectorConfig },
	options: DetectorOptions,
	{ keepDelivery, suggestConnection }: { keepDelivery: boolean; suggestConnection: boolean }
): DetectorEdit {
	const next = applyDetectorPreset(edit.detector, preset.detector, { keepDelivery });
	const connection = questionConnection(
		next,
		edit.connection,
		options.connections,
		suggestConnection
	);
	const label = presetLabel(edit, preset.id, options);
	return {
		label: label ?? edit.label,
		suggestedLabel: label ?? edit.suggestedLabel,
		detector: connection ? assignConnection(next, connection) : next,
		preset: preset.id,
		presetSettings: JSON.stringify(detectorSettings(next)),
		connection: connection?.label ?? ''
	};
}

/** The preset whose question a connection needs first, when the rule has none of its own. */
export function questionPreset(edit: DetectorEdit, presets: PresetInfo[]): string | undefined {
	return edit.detector.vlm?.[0] ? undefined : followedPreset(edit, presets)?.id;
}

/** The edit verified through a saved AI connection; `template` supplies a missing question. */
export function chooseConnection(
	edit: DetectorEdit,
	connection: LlmConnection,
	template?: DetectorConfig
): DetectorEdit {
	return {
		...edit,
		detector: assignConnection(edit.detector, connection, template),
		connection: connection.label
	};
}

/** What the editor has to tell the person after choosing a preset or a connection. */
export type DetectorEditProblem =
	| { kind: 'preset' | 'question'; cause: unknown }
	| { kind: 'no-question' };

/**
 * Bring an unfinished edit back from the choices kept in the browser. Cameras, recipients and
 * connections that no longer exist are left out. A preset or question that cannot be fetched is
 * reported, and the remaining choices are still restored.
 */
export async function restoreDetectorChoices(
	edit: DetectorEdit,
	choices: DetectorChoices,
	options: DetectorOptions,
	{ savedPreset, keepDelivery }: { savedPreset?: string; keepDelivery: boolean },
	presetDetector: (id: string) => Promise<DetectorConfig>
): Promise<{ edit: DetectorEdit; problem?: DetectorEditProblem }> {
	let problem: DetectorEditProblem | undefined;
	if (choices.preset && choices.preset !== savedPreset) {
		try {
			edit = choosePreset(
				edit,
				{ id: choices.preset, detector: await presetDetector(choices.preset) },
				options,
				{ keepDelivery, suggestConnection: false }
			);
		} catch (cause) {
			problem = { kind: 'preset', cause };
		}
	}
	const detector = createDetectorDraft(edit.detector);
	detector.detection.source = options.cameras
		.filter((camera) => choices.cameras.includes(camera.id))
		.map((camera) => camera.source);
	for (const channel of options.telegrams)
		detector.exporters.telegram = selectTelegram(
			detector.exporters.telegram ?? [],
			channel,
			choices.telegrams.includes(channel.label)
		);
	edit = { ...edit, label: choices.label, detector };
	const connection = options.connections.find((item) => item.label === choices.connection);
	if (connection) {
		try {
			const template = questionPreset(edit, options.presets);
			edit = chooseConnection(
				edit,
				connection,
				template ? await presetDetector(template) : undefined
			);
			if (lacksQuestion(edit.detector)) problem = { kind: 'no-question' };
		} catch (cause) {
			problem = { kind: 'question', cause };
		}
	}
	if (!choices.validatorEnabled)
		for (const verifier of edit.detector.vlm ?? []) verifier.key = null;
	return { edit, problem };
}

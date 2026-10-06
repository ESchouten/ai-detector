import * as v from 'valibot';
import type * as Input from './generated/config.js';
import { LOCALES } from './locales.ts';

// Validation messages are functions so each is written in the language of the request that
// fails, not fixed in whichever language was current when this module loaded.

export type { EventMetadata as Metadata } from './generated/metadata.js';
export type { TelegramConfig, VLMConfig } from './generated/config.js';

export const STAGES = ['approved', 'rejected', 'unvalidated'] as const;
export type Stage = (typeof STAGES)[number];

export const DEFAULT_SCHEMA_URL =
	'https://raw.githubusercontent.com/ESchouten/ai-detector/main/config/config.schema.json';

/** The input schema permits one destination or a list; editing always uses lists. */
export type ExportersConfig = {
	[Key in keyof Input.ExportersConfig]: Exclude<
		Input.ExportersConfig[Key],
		unknown[] | null | undefined
	>[];
};

/** Source lists may be empty while choosing a camera for a preset or draft. */
export interface DetectorConfig extends Omit<
	Input.DetectorConfig,
	'detection' | 'exporters' | 'vlm'
> {
	detection: Omit<Input.SourceConfig, 'source'> & { source: string[] };
	exporters?: ExportersConfig;
	vlm?: Input.VLMConfig[];
}

/** An empty setup is valid in the web app, before the detector can be started. */
export interface Config extends Omit<Input.Config, 'detectors'> {
	detectors: DetectorConfig[];
}

const text = v.pipe(v.string(), v.trim(), v.minLength(1));
export const detectorMeta = v.object({
	label: text,
	preset: v.optional(text),
	/** Which settings the preset gave, to tell whether the detector still follows it. */
	presetVersion: v.optional(text),
	/** Present only when the person switched off taking the preset's newer settings by itself. */
	autoUpdate: v.optional(v.literal(false)),
	llmConnection: v.optional(text)
});
export const cameraConnectionMeta = v.object({
	address: v.pipe(
		text,
		v.check(
			(value) => {
				try {
					const url = new URL(value);
					return (
						['http:', 'https:'].includes(url.protocol) &&
						!url.username &&
						!url.password &&
						!url.search &&
						!url.hash
					);
				} catch {
					return false;
				}
			},
			() => 'Camera connection details must not contain login details or access tokens.'
		)
	),
	profileToken: v.optional(text)
});
const timestamp = v.pipe(v.string(), v.isoTimestamp());
const cameraSetup = v.object({
	pictureVerifiedAt: v.optional(timestamp),
	archiveVerifiedAt: v.optional(timestamp),
	archiveSignature: v.optional(text),
	alerts: v.optional(v.literal('skipped')),
	completedAt: v.optional(timestamp),
	completionSignature: v.optional(text)
});
export const streamMeta = v.object({
	id: v.optional(text),
	label: v.optional(text),
	source: text,
	connection: v.optional(cameraConnectionMeta),
	setup: v.optional(cameraSetup)
});
const identity = v.pipe(v.string(), v.minLength(1));
const clockTime = v.pipe(
	v.string(),
	v.regex(/^([01]\d|2[0-3]):[0-5]\d$/, () => 'Enter a time such as 22:00.')
);
export const telegramMeta = v.object({
	label: text,
	token: identity,
	chat: identity,
	/** Alerts between these times of day arrive without sound. */
	quiet: v.optional(v.object({ start: clockTime, end: clockTime }))
});
const headerName = v.pipe(
	text,
	v.regex(/^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/, () => 'Enter a valid header name.')
);
const headerValue = v.pipe(
	v.string(),
	v.check(
		(value) => !/[\r\n]/.test(value),
		() => 'Use a single-line header value.'
	)
);
const modelName = v.pipe(
	v.string(),
	v.trim(),
	v.minLength(1, () => 'Enter a model name.'),
	v.check(
		(value) => !/\s/.test(value) && !value.endsWith('/'),
		() => 'Enter a model name, without spaces or a trailing slash.'
	)
);
export const llmConnection = v.object({
	label: v.pipe(
		v.string(),
		v.trim(),
		v.minLength(1, () => 'Enter a connection name.')
	),
	model: v.union([
		modelName,
		v.pipe(
			v.array(modelName),
			v.minLength(1, () => 'Enter at least one model.')
		)
	]),
	key: v.optional(v.nullable(v.string())),
	url: v.optional(
		v.nullable(
			v.pipe(
				text,
				v.url(),
				v.regex(/^https?:\/\//i, () => 'Use an HTTP or HTTPS API URL.')
			)
		)
	),
	headers: v.optional(
		v.pipe(
			v.record(headerName, headerValue),
			v.check(
				(headers) =>
					new Set(Object.keys(headers).map((name) => name.toLowerCase())).size ===
					Object.keys(headers).length,
				() => 'Each header name must be unique.'
			)
		)
	)
});
const pairedDevice = v.object({
	id: v.string(),
	name: v.string(),
	hash: v.string(),
	created: v.number(),
	expires: v.number()
});
// app.json also holds `monitoring`, the detector launcher's resume flag (see monitoring-flag.ts).
// It is deliberately absent here, so settings documents, backups and revisions never contain it.
export const appSchema = v.object({
	// The interface language of this installation; absent until setup or a choice records one.
	// A value this version does not know must not make the other settings unreadable.
	language: v.fallback(v.optional(v.picklist(LOCALES)), undefined),
	streams: v.optional(v.array(streamMeta), []),
	telegrams: v.optional(v.array(telegramMeta), []),
	llms: v.optional(v.array(llmConnection), []),
	detectors: v.optional(v.array(detectorMeta), []),
	devices: v.optional(v.array(pairedDevice))
});

export type AppConfig = v.InferOutput<typeof appSchema>;
export type PairedDevice = v.InferOutput<typeof pairedDevice>;
export type DetectorMeta = v.InferOutput<typeof detectorMeta>;
export type TelegramMeta = v.InferOutput<typeof telegramMeta>;
export type LlmConnection = v.InferOutput<typeof llmConnection>;
export type StreamMeta = v.InferOutput<typeof streamMeta>;
export type CameraSetup = v.InferOutput<typeof cameraSetup>;

export interface PresetInfo {
	id: string;
	name: string;
}

export interface DetectorPreset extends PresetInfo {
	detector: DetectorConfig;
}

export interface Configuration {
	config: Config;
	app: AppConfig;
}

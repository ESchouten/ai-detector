import * as v from 'valibot';
import type * as Input from './generated/config.js';

export type { EventMetadata as Metadata } from './generated/metadata.js';
export type { TelegramConfig } from './generated/config.js';

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
export interface DetectorConfig extends Omit<Input.DetectorConfig, 'detection' | 'exporters'> {
	detection: Omit<Input.SourceConfig, 'source'> & { source: string[] };
	exporters?: ExportersConfig;
}

/** An empty setup is valid in the web app, before the detector can be started. */
export interface Config extends Omit<Input.Config, 'detectors'> {
	detectors: DetectorConfig[];
}

const text = v.pipe(v.string(), v.trim(), v.minLength(1));
export const detectorMeta = v.object({
	label: text,
	cameraId: v.optional(text),
	preset: v.optional(text)
});
export const cameraConnectionMeta = v.object({
	address: v.pipe(
		text,
		v.check((value) => {
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
		}, 'Camera connection details must not contain login details or access tokens.')
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
export const telegramMeta = v.object({ label: text, token: identity, chat: identity });
export const appSchema = v.object({
	streams: v.optional(v.array(streamMeta), []),
	telegrams: v.optional(v.array(telegramMeta), []),
	detectors: v.optional(v.array(detectorMeta), [])
});

export type AppConfig = v.InferOutput<typeof appSchema>;
export type DetectorMeta = v.InferOutput<typeof detectorMeta>;
export type TelegramMeta = v.InferOutput<typeof telegramMeta>;
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

export const STAGES = ['approved', 'rejected', 'unvalidated'] as const;
export type Stage = (typeof STAGES)[number];

export interface Metadata {
	type: string;
	timestamp: string;
	validated: boolean | null;
	confidence: number;
	start: string;
	end: string;
	duration: number;
}

export const DEFAULT_SCHEMA_URL =
	'https://raw.githubusercontent.com/ESchouten/ai-detector/main/config/config.schema.json';

export interface DetectorConfig {
	detection: {
		source: string[];
		interval?: number;
		[key: string]: unknown;
	};
	yolo?: {
		model: string;
		confidence?: number | Record<string, number>;
		frames_min?: number;
		iou?: number | null;
		tracking?: boolean;
		tracker?: 'botsort.yaml' | 'bytetrack.yaml' | null;
		[key: string]: unknown;
	} | null;
	exporters?: {
		telegram?: TelegramConfig[];
		[key: string]: unknown[] | undefined;
	};
	[key: string]: unknown;
}

export interface TelegramConfig {
	token: string;
	chat: string;
	alert_every?: number;
	[key: string]: unknown;
}

export interface Config {
	$schema?: string | null;
	detectors: DetectorConfig[];
	[key: string]: unknown;
}

export interface AppConfig {
	streams: StreamMeta[];
	telegrams: TelegramMeta[];
	detectors: DetectorMeta[];
}

export interface DetectorMeta {
	label: string;
	cameraId?: string;
	preset?: string;
}

export interface PresetInfo {
	id: string;
	name: string;
	description: string;
	guidance?: string;
}

export interface DetectorPreset extends PresetInfo {
	detector: DetectorConfig;
}

export interface PresetCatalog {
	defaultPreset?: string;
	presets: DetectorPreset[];
}

export interface TelegramMeta extends TelegramConfig {
	label: string;
}

export interface StreamMeta {
	id?: string;
	label?: string;
	source: string;
	connection?: { address: string; profileToken?: string };
	setup?: CameraSetup;
}

export interface CameraSetup {
	pictureVerifiedAt?: string;
	archiveVerifiedAt?: string;
	archiveSignature?: string;
	alerts?: 'skipped';
	completedAt?: string;
	completionSignature?: string;
}

export interface Configuration {
	config: Config;
	app: AppConfig;
}

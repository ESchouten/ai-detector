/** Generated from config/config.schema.json. Run pnpm schema:generate; do not edit. */

export type $Schema = string | null;
/**
 * @minItems 1
 */
export type Detectors = [DetectorConfig, ...DetectorConfig[]];
export type Source = string | [string, ...string[]];
export type Interval = number;
export type FrameRetention = number;
export type FramesWidth = number;
export type Model = string;
export type Task = 'detect' | 'segment';
export type Confidence =
	| number
	| {
			/**
			 * This interface was referenced by `undefined`'s JSON-Schema definition
			 * via the `patternProperty` "\S".
			 */
			[k: string]: number;
	  };
export type Tracking = boolean;
export type TimeMax = number;
export type Timeout = number;
export type Cooldown =
	| number
	| {
			/**
			 * This interface was referenced by `undefined`'s JSON-Schema definition
			 * via the `patternProperty` "\S".
			 */
			[k: string]: number;
	  };
export type IncludeTrailingTime = number;
export type FramesMin = number;
export type Imgsz = number;
export type Iou = number | null;
export type Tracker = ('botsort.yaml' | 'bytetrack.yaml') | null;
export type Vlm = VLMConfig | VLMConfig[] | null;
export type Prompt = string;
export type Model1 = string | [string, ...string[]];
export type Key = string | null;
export type Url = string | null;
export type Strategy = 'IMAGE' | 'VIDEO';
export type CropPadding = number;
export type Timeout1 = number;
export type Attempts = number;
export type Disk = DiskConfig | DiskConfig[] | null;
export type Confidence1 =
	| number
	| {
			/**
			 * This interface was referenced by `undefined`'s JSON-Schema definition
			 * via the `patternProperty` "\S".
			 */
			[k: string]: number;
	  }
	| null;
export type CropPadding1 = number;
export type ExportRejected = boolean;
/**
 * Single category directory name under detections/.
 */
export type Directory = string | null;
export type Strategy1 = 'ALL' | 'BEST';
export type Telegram = TelegramConfig | TelegramConfig[] | null;
export type Confidence2 =
	| number
	| {
			/**
			 * This interface was referenced by `undefined`'s JSON-Schema definition
			 * via the `patternProperty` "\S".
			 */
			[k: string]: number;
	  }
	| null;
export type CropPadding2 = number;
export type ExportRejected1 = boolean;
export type IncludeImage = boolean;
export type IncludePlot = boolean;
export type IncludeCrop = boolean;
export type IncludeVideo = boolean;
export type VideoWidth = number | null;
export type VideoCrf = number;
export type Token = string;
export type Chat = string;
export type AlertEvery = number;
export type Timeout2 = number;
export type Webhook = WebhookConfig | WebhookConfig[] | null;
export type Url1 = string;
export type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE' | 'HEAD';
export type Timeout3 = number;
export type Headers = {
	[k: string]: string;
} | null;
export type Body = string | null;
export type Confidence3 =
	| number
	| {
			/**
			 * This interface was referenced by `undefined`'s JSON-Schema definition
			 * via the `patternProperty` "\S".
			 */
			[k: string]: number;
	  }
	| null;
export type CropPadding3 = number;
export type ExportRejected2 = boolean;
export type IncludeImage1 = boolean;
export type IncludePlot1 = boolean;
export type IncludeCrop1 = boolean;
export type IncludeVideo1 = boolean;
export type VideoWidth1 = number | null;
export type VideoCrf1 = number;
export type Token1 = string | null;
export type DataType = 'binary' | 'base64' | 'none';
export type DataMax = number | null;
export type PendingEvents = number;
export type Provider = string | null;
export type Winml = boolean;
export type Opset = number;
export type Url2 = string;
export type Method1 = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE' | 'HEAD';
export type Timeout4 = number;
export type Headers1 = {
	[k: string]: string;
} | null;
export type Body1 = string | null;
export type Interval1 = number;

export interface Config {
	$schema?: $Schema;
	detectors: Detectors;
	onnx?: OnnxConfig;
	health?: HealthcheckConfig | null;
}
export interface DetectorConfig {
	detection: SourceConfig;
	yolo?: YoloConfig | null;
	vlm?: Vlm;
	exporters?: ExportersConfig | null;
	pending_events?: PendingEvents;
}
export interface SourceConfig {
	source: Source;
	interval?: Interval;
	frame_retention?: FrameRetention;
	frames_width?: FramesWidth;
}
export interface YoloConfig {
	model: Model;
	task?: Task;
	confidence?: Confidence;
	tracking?: Tracking;
	time_max?: TimeMax;
	timeout?: Timeout;
	cooldown?: Cooldown;
	include_trailing_time?: IncludeTrailingTime;
	frames_min?: FramesMin;
	imgsz?: Imgsz;
	iou?: Iou;
	tracker?: Tracker;
}
export interface VLMConfig {
	prompt: Prompt;
	model: Model1;
	key?: Key;
	url?: Url;
	strategy?: Strategy;
	crop_padding?: CropPadding;
	timeout?: Timeout1;
	attempts?: Attempts;
}
export interface ExportersConfig {
	disk?: Disk;
	telegram?: Telegram;
	webhook?: Webhook;
}
export interface DiskConfig {
	confidence?: Confidence1;
	crop_padding?: CropPadding1;
	export_rejected?: ExportRejected;
	directory?: Directory;
	strategy?: Strategy1;
}
export interface TelegramConfig {
	confidence?: Confidence2;
	crop_padding?: CropPadding2;
	export_rejected?: ExportRejected1;
	include_image?: IncludeImage;
	include_plot?: IncludePlot;
	include_crop?: IncludeCrop;
	include_video?: IncludeVideo;
	video_width?: VideoWidth;
	video_crf?: VideoCrf;
	token: Token;
	chat: Chat;
	alert_every?: AlertEvery;
	timeout?: Timeout2;
}
export interface WebhookConfig {
	url: Url1;
	method?: Method;
	timeout?: Timeout3;
	headers?: Headers;
	body?: Body;
	confidence?: Confidence3;
	crop_padding?: CropPadding3;
	export_rejected?: ExportRejected2;
	include_image?: IncludeImage1;
	include_plot?: IncludePlot1;
	include_crop?: IncludeCrop1;
	include_video?: IncludeVideo1;
	video_width?: VideoWidth1;
	video_crf?: VideoCrf1;
	token?: Token1;
	data_type?: DataType;
	data_max?: DataMax;
}
export interface OnnxConfig {
	provider?: Provider;
	winml?: Winml;
	opset?: Opset;
}
export interface HealthcheckConfig {
	url: Url2;
	method?: Method1;
	timeout?: Timeout4;
	headers?: Headers1;
	body?: Body1;
	interval?: Interval1;
}

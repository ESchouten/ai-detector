import * as v from 'valibot';
import type { AppConfig, Config, DetectorConfig } from '../../schema.ts';
import { DEFAULT_SCHEMA_URL } from '../../schema.ts';
import { configurationSchema } from '../../configuration.ts';
import calving from '../../../../../config/detector/calving-catcher.json' with { type: 'json' };
import mounts from '../../../../../config/detector/cow-catcher.json' with { type: 'json' };

export const detectorPresets: Record<string, DetectorConfig> = {
	'calving-catcher.json': {
		...calving,
		detection: { ...calving.detection, source: [] },
		exporters: { disk: [calving.exporters.disk] }
	},
	'cow-catcher.json': {
		...mounts,
		detection: { source: [] },
		exporters: { disk: [mounts.exporters.disk] }
	}
};

const editorSchema = v.looseObject({
	$defs: v.looseObject({ DetectorConfig: v.record(v.string(), v.unknown()) })
});

export async function getEditorSchema(schemaUrl?: string | null) {
	if (!schemaUrl || schemaUrl === DEFAULT_SCHEMA_URL) return configurationSchema;
	try {
		const response = await fetch(schemaUrl, { signal: AbortSignal.timeout(10000) });
		if (!response.ok) return configurationSchema;
		return v.parse(editorSchema, await response.json());
	} catch {
		return configurationSchema;
	}
}

export const setupInput = v.object({
	label: v.pipe(v.string(), v.trim(), v.minLength(1, 'Give this camera a name.')),
	source: v.pipe(
		v.string(),
		v.trim(),
		v.check((value) => {
			try {
				const url = new URL(value);
				return ['rtsp:', 'rtsps:', 'http:', 'https:'].includes(url.protocol) && !!url.hostname;
			} catch {
				return false;
			}
		}, 'Enter the camera’s RTSP or HTTP stream address.')
	),
	preset: v.picklist(['calving', 'mounts', 'general'])
});

export function initialSetup(input: v.InferOutput<typeof setupInput>): {
	config: Config;
	app: AppConfig;
} {
	const preset =
		input.preset === 'calving'
			? calving
			: input.preset === 'mounts'
				? mounts
				: {
						yolo: { model: 'yolo11n.pt', confidence: 0.5, frames_min: 3 },
						exporters: { disk: {} }
					};
	const detector: DetectorConfig = {
		...preset,
		detection: { ...('detection' in preset ? preset.detection : {}), source: [input.source] },
		exporters: { disk: [preset.exporters.disk] }
	};
	return {
		config: { detectors: [detector] },
		app: {
			streams: [{ label: input.label, source: input.source }],
			telegrams: [],
			detectors: [{ label: input.label }]
		}
	};
}

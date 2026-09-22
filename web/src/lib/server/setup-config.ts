import * as v from 'valibot';
import type { AppConfig, Config, DetectorConfig } from '../schema';
import calving from '../../../../config/detector/calving-catcher.json';
import mounts from '../../../../config/detector/cow-catcher.json';

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

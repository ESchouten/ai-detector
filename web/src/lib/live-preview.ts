import * as v from 'valibot';

const coordinate = v.pipe(v.number(), v.finite());
/** One actual analyzed frame, with coordinates in the included image's pixels. */
export const frameSchema = v.object({
	version: v.literal(1),
	runId: v.string(),
	sourceKey: v.string(),
	ruleId: v.string(),
	capturedAt: v.string(),
	publishedAt: v.pipe(v.string(), v.isoTimestamp()),
	capture: v.optional(
		v.object({
			epoch: v.pipe(v.string(), v.minLength(1)),
			sequence: v.pipe(v.number(), v.integer(), v.minValue(0))
		})
	),
	image: v.object({
		width: v.pipe(v.number(), v.integer(), v.minValue(1)),
		height: v.pipe(v.number(), v.integer(), v.minValue(1)),
		jpeg: v.pipe(v.string(), v.minLength(1))
	}),
	boxes: v.array(
		v.object({
			x1: coordinate,
			y1: coordinate,
			x2: coordinate,
			y2: coordinate,
			label: v.nullable(v.string()),
			confidence: v.nullable(coordinate),
			trackId: v.nullable(v.pipe(v.number(), v.integer())),
			identity: v.optional(
				v.object({
					id: v.nullable(v.string()),
					name: v.nullable(v.string()),
					similarity: v.nullable(coordinate)
				})
			)
		})
	)
});

/** The web app adds the configured label to the detector's frame. */
export type LivePreviewFrame = v.InferOutput<typeof frameSchema> & {
	ruleLabel: string;
	rulePreset?: string;
};

/** Geometry only: camera cards keep playing their independent live video. */
export type CameraOverlayFrame = Omit<LivePreviewFrame, 'image'> & {
	cameraId: string;
	image: { width: number; height: number };
};

export function detectionBoxLabel(box: LivePreviewFrame['boxes'][number]): string {
	if (box.identity) {
		return box.identity.id && box.identity.name ? `Possible ${box.identity.name}` : 'Unknown';
	}
	return [
		box.label,
		box.confidence === null ? null : `${Math.round(box.confidence * 100)}%`,
		box.trackId === null ? null : `#${box.trackId}`
	]
		.filter((part) => part !== null)
		.join(' · ');
}

export interface LivePreviewStatus {
	version: 1;
	state: 'waiting' | 'unavailable';
	message: string;
	ruleId?: string;
	ruleLabel?: string;
	rulePreset?: string;
	cameraId?: string;
}

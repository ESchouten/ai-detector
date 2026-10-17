import * as v from 'valibot';

const coordinate = v.pipe(v.number(), v.finite());
/** The boxes of one analyzed picture, with coordinates in pixels of the given image size. */
export const frameSchema = v.object({
	version: v.literal(1),
	runId: v.string(),
	sourceKey: v.string(),
	ruleId: v.string(),
	publishedAt: v.pipe(v.string(), v.isoTimestamp()),
	image: v.object({
		width: v.pipe(v.number(), v.integer(), v.minValue(1)),
		height: v.pipe(v.number(), v.integer(), v.minValue(1))
	}),
	boxes: v.array(
		v.object({
			x1: coordinate,
			y1: coordinate,
			x2: coordinate,
			y2: coordinate,
			label: v.nullable(v.string()),
			confidence: v.nullable(coordinate),
			trackId: v.nullable(v.pipe(v.number(), v.integer()))
		})
	)
});

/** The web app adds the configured label to the detector's frame. */
export type LivePreviewFrame = v.InferOutput<typeof frameSchema> & {
	ruleLabel: string;
	rulePreset?: string;
};

/** One connection carries the frames of every visible camera, so each names its camera. */
export type CameraOverlayFrame = LivePreviewFrame & { cameraId: string };

export function detectionBoxLabel(box: LivePreviewFrame['boxes'][number]): string {
	return [
		box.label,
		box.confidence === null ? null : `${Math.round(box.confidence * 100)}%`,
		box.trackId === null ? null : `#${box.trackId}`
	]
		.filter((part) => part !== null)
		.join(' · ');
}

/** Clears the boxes of one camera's rule, or of every camera when it names none. */
export interface LivePreviewStatus {
	ruleId?: string;
	cameraId?: string;
}

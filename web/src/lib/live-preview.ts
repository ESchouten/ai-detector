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
			trackId: v.nullable(v.pipe(v.number(), v.integer()))
		})
	)
});

/** The web app adds the configured label to the detector's frame. */
export type LivePreviewFrame = v.InferOutput<typeof frameSchema> & { ruleLabel: string };

export interface LivePreviewStatus {
	version: 1;
	state: 'waiting' | 'unavailable';
	message: string;
	ruleId?: string;
	ruleLabel?: string;
}

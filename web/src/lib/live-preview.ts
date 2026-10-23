import * as v from 'valibot';

const coordinate = v.pipe(v.number(), v.finite());
/** Who a tracked box is, once the detector saved its pictures as a sighting. */
const identitySchema = v.object({
	sighting: v.pipe(v.string(), v.regex(/^[a-f0-9]{32}$/)),
	/** Set when the detector recognises it, or a person named this sighting. */
	name: v.nullable(v.string()),
	/** The named identities it resembles most, best first. */
	candidates: v.array(v.object({ name: v.string(), score: coordinate }))
});
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
			trackId: v.nullable(v.pipe(v.number(), v.integer())),
			identity: v.nullable(identitySchema)
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

export type DetectionBox = LivePreviewFrame['boxes'][number];

/** `412` when recognised, `412?` when it only resembles 412, nothing before anything is named. */
export function identityLabel(identity: DetectionBox['identity']): string | null {
	if (!identity) return null;
	if (identity.name !== null) return identity.name;
	return identity.candidates.length ? `${identity.candidates[0].name}?` : null;
}

export function detectionBoxLabel(box: DetectionBox): string {
	const identity = identityLabel(box.identity);
	return [
		identity ?? box.label,
		identity !== null || box.confidence === null ? null : `${Math.round(box.confidence * 100)}%`,
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

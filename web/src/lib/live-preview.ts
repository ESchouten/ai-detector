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
			/** Points around a tracked individual when the detector's model segments. */
			outline: v.array(v.tuple([coordinate, coordinate])),
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

/** The points to draw around a box: its outline, or else its corners. */
export function boxOutline(box: DetectionBox): string {
	const points =
		box.outline.length > 2
			? box.outline
			: [
					[box.x1, box.y1],
					[box.x2, box.y1],
					[box.x2, box.y2],
					[box.x1, box.y2]
				];
	return points.map(([x, y]) => `${x},${y}`).join(' ');
}

/** `412` when recognised, `412?` when it only resembles 412, nothing before anything is named. */
export function identityLabel(identity: DetectionBox['identity']): string | null {
	if (!identity) return null;
	if (identity.name !== null) return identity.name;
	return identity.candidates.length ? `${identity.candidates[0].name}?` : null;
}

/** Recognised, only resembling a name, or not named at all. */
export type IdentityState = 'recognised' | 'resembles' | 'unnamed';

export function identityState(identity: NonNullable<DetectionBox['identity']>): IdentityState {
	if (identity.name !== null) return 'recognised';
	return identity.candidates.length ? 'resembles' : 'unnamed';
}

/** A box shows who it is as a pill once it resembles someone, and while naming always. */
export function showsPill(box: DetectionBox, naming: boolean): boolean {
	return box.identity !== null && (naming || identityState(box.identity) !== 'unnamed');
}

/** Where a box's pill points: the top of its outline nearest the middle, so an
 * outline cut off along the picture's top edge points at its middle; without an
 * outline, the middle of the box's top side. */
export function pillAnchor(box: DetectionBox): [number, number] {
	const middle = (box.x1 + box.x2) / 2;
	if (box.outline.length <= 2) return [middle, box.y1];
	const top = Math.min(...box.outline.map(([, y]) => y));
	const near = Math.max(2, (box.y2 - box.y1) * 0.03);
	return box.outline
		.filter(([, y]) => y <= top + near)
		.reduce((best, point) =>
			Math.abs(point[0] - middle) < Math.abs(best[0] - middle) ? point : best
		);
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

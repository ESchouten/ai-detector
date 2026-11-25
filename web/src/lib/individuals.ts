import * as v from 'valibot';

/** One track's pictures from one event, as the detector saved them. */
export interface Sighting {
	id: string;
	/** The source time of the event, in the detector computer's local time. */
	seen: string;
	/** How many pictures it has: crop-1.jpg and onwards. */
	crops: number;
	/** Each picture's outline as [x, y] points in its pixels; none without segmentation. */
	outlines: [number, number][][];
	/**
	 * The number the detector read from the tag it wears, for a person to confirm: read from
	 * tag-read.jpg, which is the part `box` (x1, y1, x2, y2) of tag-picture.jpg.
	 */
	tag: { number: string; box: [number, number, number, number] } | null;
}

/** Unnamed sightings that look alike, to name at once. */
export interface SightingGroup {
	/** Every sighting of the group; only the first few are in `shown`. */
	ids: string[];
	shown: Sighting[];
	/** Named individuals the group resembles most, best first. */
	suggestions: string[];
	/** The latest named sighting of the first suggestion, to compare the group with. */
	reference: Sighting | null;
}

export interface NamedIndividual {
	name: string;
	/** Its latest sightings first; only the first few are in `shown`. */
	ids: string[];
	shown: Sighting[];
	/** On how many days its named sightings were seen. */
	days: number;
}

/**
 * From how many days an individual needs named sightings. With fewer it is recognised less often,
 * and with one or two named sightings it is given the name of one that looks like it.
 */
export const DAYS_WANTED = 3;

export interface IndividualsOverview {
	groups: SightingGroup[];
	/** Groups after the ones listed. */
	moreGroups: number;
	unnamed: number;
	named: NamedIndividual[];
	/** On how many days the named sightings were seen; recognition needs two. */
	namedDays: number;
}

export const sightingIdInput = v.pipe(v.string(), v.regex(/^[a-f0-9]{32}$/));

export const individualNameInput = v.pipe(
	v.string(),
	v.trim(),
	v.minLength(1, () => 'Enter a name or number.'),
	v.maxLength(40, () => 'Use at most 40 characters.')
);

export const nameSightingsInput = v.object({
	sightings: v.pipe(
		v.array(sightingIdInput),
		v.minLength(1, () => 'Keep at least one picture to name.')
	),
	name: individualNameInput,
	/** Whether the name was a Yes to the detector's guess. */
	confirmed: v.boolean()
});

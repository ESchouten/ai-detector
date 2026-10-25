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
}

/** Unnamed sightings that look alike, to name at once. */
export interface SightingGroup {
	/** Every sighting of the group; only the first few are in `shown`. */
	ids: string[];
	shown: Sighting[];
	/** Named individuals the group resembles most, best first. */
	suggestions: string[];
}

export interface NamedIndividual {
	name: string;
	/** Its latest sightings first; only the first few are in `shown`. */
	ids: string[];
	shown: Sighting[];
}

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
	name: individualNameInput
});

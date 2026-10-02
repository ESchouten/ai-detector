import * as v from 'valibot';

// Persist references to server settings, never camera URLs or connection credentials.
const choicesSchema = v.object({
	label: v.string(),
	preset: v.string(),
	cameras: v.array(v.string()),
	telegrams: v.array(v.string()),
	connection: v.string(),
	validatorEnabled: v.boolean()
});

export type DetectorChoices = v.InferOutput<typeof choicesSchema>;
type DraftStorage = () => Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
const browserStorage: DraftStorage = () => sessionStorage;

export function readDetectorChoices(key: string, storage = browserStorage): DetectorChoices | null {
	try {
		const saved = storage().getItem(key);
		return saved ? v.parse(choicesSchema, JSON.parse(saved)) : null;
	} catch {
		// Drafts are optional: disabled storage and old or damaged drafts start fresh.
		return null;
	}
}

export function writeDetectorChoices(
	key: string,
	choices: DetectorChoices | null,
	storage = browserStorage
): void {
	try {
		if (choices) storage().setItem(key, JSON.stringify(choices));
		else storage().removeItem(key);
	} catch {
		// A full or disabled browser store must not interrupt editing or navigation.
	}
}

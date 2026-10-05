import { fail } from '@sveltejs/kit';
import { plural } from '$lib/format';
import * as v from 'valibot';
import { DATA_DIRECTORY } from '$lib/server/application-paths';
import { recordings } from '$lib/server/recordings';
import { configuration } from '$lib/server/configuration';
import { managedDetector } from '$lib/server/detector-service';
import {
	diskSpace,
	recordingCleanup,
	removeRecordings,
	clearModelCache
} from '$lib/server/storage';
import type { Actions, PageServerLoad } from './$types';

const beforeDate = v.pipe(
	v.string(),
	v.isoDate(),
	v.check(
		(value) =>
			new Date(value).toJSON()?.slice(0, 10) === value &&
			value <= new Date().toISOString().slice(0, 10),
		() => 'Choose today or an earlier date.'
	)
);
export const load: PageServerLoad = async () => ({
	space: await diskSpace(recordings.directory),
	managed: !!managedDetector()
});

export const actions: Actions = {
	preview: async ({ request }) => {
		const form = await request.formData();
		const parsed = v.safeParse(beforeDate, form.get('before'));
		if (!parsed.success) return fail(400, { message: 'Choose a valid date, today or earlier.' });
		const { count, revision } = await recordingCleanup(recordings, parsed.output);
		return { before: parsed.output, count, revision };
	},
	remove: async ({ request }) => {
		const form = await request.formData();
		const parsed = v.safeParse(beforeDate, form.get('before'));
		if (!parsed.success) return fail(400, { message: 'Choose a valid date, today or earlier.' });
		try {
			const count = await removeRecordings(
				recordings,
				parsed.output,
				String(form.get('revision') ?? '')
			);
			return { message: plural(count, ['Removed # recording.', 'Removed # recordings.']) };
		} catch (error) {
			return fail(400, {
				message: error instanceof Error ? error.message : 'Recordings could not be removed.'
			});
		}
	},
	cache: async () => {
		const detector = managedDetector();
		if (!detector)
			return fail(400, {
				message: 'Cache cleanup requires the desktop application so monitoring can be checked.'
			});
		try {
			const { config } = await configuration.read();
			await detector.whileStopped(() => clearModelCache(DATA_DIRECTORY, config));
			return {
				message:
					'Prepared models and unused model downloads removed. Current source models were kept.'
			};
		} catch (error) {
			return fail(400, {
				message: error instanceof Error ? error.message : 'The cache could not be cleared.'
			});
		}
	}
};

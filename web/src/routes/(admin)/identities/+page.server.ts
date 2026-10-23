import { fail } from '@sveltejs/kit';
import * as v from 'valibot';
import { nameSightingsInput, sightingIdInput } from '$lib/individuals';
import { configuration } from '$lib/server/configuration';
import { individuals } from '$lib/server/individuals';
import { SightingMissingError } from '$lib/server/individuals-folder';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async () => {
	const { app, config } = await configuration.read();
	// Identities are recognised per track, so only cameras a tracking detector watches show them.
	const cameras = app.streams
		.filter((camera) =>
			config.detectors.some(
				(rule) => rule.yolo?.tracking && rule.detection.source.includes(camera.source)
			)
		)
		.map((camera) => ({ id: camera.id, label: camera.label ?? 'Camera' }));
	return { overview: await individuals.overview(), cameras };
};

export const actions: Actions = {
	name: async ({ request }) => {
		const form = await request.formData();
		const parsed = v.safeParse(nameSightingsInput, {
			sightings: form.getAll('sighting'),
			name: form.get('name') ?? ''
		});
		if (!parsed.success) return fail(400, { message: parsed.issues[0].message });
		try {
			await individuals.name(parsed.output.sightings, parsed.output.name);
		} catch (error) {
			if (error instanceof SightingMissingError) return fail(400, { message: error.message });
			throw error;
		}
		return { named: parsed.output.name };
	},
	unname: async ({ request }) => {
		const form = await request.formData();
		const parsed = v.safeParse(v.array(sightingIdInput), form.getAll('sighting'));
		if (!parsed.success) return fail(400, { message: 'Reload the page and try again.' });
		await individuals.unname(parsed.output);
	}
};

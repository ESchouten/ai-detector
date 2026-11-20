import { error } from '@sveltejs/kit';
import { command, query } from '$app/server';
import * as v from 'valibot';
import { individualNameInput, sightingIdInput } from '$lib/individuals';
import { individuals } from '$lib/server/individuals';
import { SightingMissingError } from '$lib/server/individuals-folder';

export const getSighting = query(sightingIdInput, (id) => individuals.sighting(id));

/** Names the sighting a live box shows, as naming it on the Identities page does. */
export const nameSighting = command(
	v.object({ sighting: sightingIdInput, name: individualNameInput, confirmed: v.boolean() }),
	async ({ sighting, name, confirmed }) => {
		try {
			await individuals.name([sighting], name, confirmed);
		} catch (failure) {
			if (failure instanceof SightingMissingError) error(400, failure.message);
			throw failure;
		}
	}
);

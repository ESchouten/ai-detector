import { redirect } from '@sveltejs/kit';
import { resolve } from '$app/paths';
import { configuration } from '$lib/server/configuration';
import { setupStep } from '$lib/setup';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ url }) => {
	const { app, config } = await configuration.read();
	const requested = url.searchParams.get('step');
	const step = setupStep(requested, app.streams.length, config.detectors.length);
	// Keep the step in the address: saving the first camera or detector must not change the page
	// under someone who is still adding more.
	if (requested !== step) redirect(302, resolve(`/setup?step=${step}`));
};

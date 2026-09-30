import { redirect } from '@sveltejs/kit';
import { resolve } from '$app/paths';
import { configuration } from '$lib/server/configuration';
import { setupStep } from '$lib/setup';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ url }) => {
	const { app, config } = await configuration.read();
	const step = setupStep(url.searchParams.get('step'), app.streams.length, config.detectors.length);
	const item = step === 'cameras' ? 'camera' : 'detector';
	const empty = step === 'cameras' ? !app.streams.length : !config.detectors.length;
	// Make the first editor explicit so saving one camera in a batch keeps the rest open.
	if (
		step !== 'finish' &&
		empty &&
		!url.searchParams.has(item) &&
		url.searchParams.get('add') !== item
	) {
		redirect(302, resolve(`/setup?step=${step}&add=${item}`));
	}
};

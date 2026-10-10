import { redirect } from '@sveltejs/kit';
import { resolve } from '$app/paths';
import type { PageServerLoad } from './$types';

/** The released web application edited a saved detector through this page. */
export const load: PageServerLoad = ({ url }) => {
	const selected = url.searchParams.get('label');
	if (selected) redirect(302, resolve(`/detectors/edit?label=${encodeURIComponent(selected)}`));
};

import { redirect } from '@sveltejs/kit';
import { resolve } from '$app/paths';
import type { PageServerLoad } from './$types';

/** Older bookmarks opened a saved camera through this page. */
export const load: PageServerLoad = ({ url }) => {
	const selected = url.searchParams.get('id');
	if (selected) redirect(302, resolve(`/streams/${encodeURIComponent(selected)}`));
};

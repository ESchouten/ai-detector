import { redirect } from '@sveltejs/kit';
import { resolve } from '$app/paths';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = ({ url }) => {
	const selected = url.searchParams.get('id');
	redirect(
		302,
		resolve(
			selected
				? `/setup?step=cameras&camera=${encodeURIComponent(selected)}`
				: '/setup?step=cameras&add=camera'
		)
	);
};

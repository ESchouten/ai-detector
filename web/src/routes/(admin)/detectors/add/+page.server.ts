import { redirect } from '@sveltejs/kit';
import { resolve } from '$app/paths';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = ({ url }) => {
	const selected = url.searchParams.get('label');
	redirect(
		302,
		resolve(
			selected
				? `/setup?step=detectors&detector=${encodeURIComponent(selected)}`
				: '/setup?step=detectors&add=detector'
		)
	);
};

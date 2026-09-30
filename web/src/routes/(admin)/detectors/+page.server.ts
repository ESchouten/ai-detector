import { redirect } from '@sveltejs/kit';
import { resolve } from '$app/paths';

export function load() {
	redirect(302, resolve('/setup?step=detectors'));
}

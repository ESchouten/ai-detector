import { error } from '@sveltejs/kit';
import { ConfigurationError } from '$lib/configuration';
import { configuration } from '$lib/server/configuration';
import type { LayoutServerLoad } from './$types';

/**
 * Every page here needs readable settings. Finding out here shows the reason and the way to
 * recover on one page, instead of each page failing in its own way while it renders.
 */
export const load: LayoutServerLoad = async () => {
	try {
		await configuration.read();
	} catch (cause) {
		if (cause instanceof ConfigurationError) error(500, cause.message);
		throw cause;
	}
};

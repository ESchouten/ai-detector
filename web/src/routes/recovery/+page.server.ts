import { fail, redirect } from '@sveltejs/kit';
import { configuration } from '$lib/server/configuration';
import { managedDetector } from '$lib/server/detector-service';
import { webLog } from '$lib/server/web-log';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async () => {
	try {
		return { available: await configuration.recoveryAvailable() };
	} catch (error) {
		webLog.error('Could not read the settings recovery snapshot', error);
		return { available: false };
	}
};

export const actions: Actions = {
	default: async () => {
		try {
			await configuration.restore();
			await managedDetector()?.initialize();
		} catch (error) {
			webLog.error('Could not restore the saved settings', error);
			return fail(400, {
				message: 'The saved settings could not be restored. Download diagnostics for help.'
			});
		}
		redirect(303, '/setup');
	}
};

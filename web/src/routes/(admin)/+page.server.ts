import { redirect } from '@sveltejs/kit';
import { configuration } from '$lib/server/configuration';

export async function load() {
	const { config } = await configuration.read();
	redirect(302, config.detectors.length > 0 ? '/detections' : '/setup');
}

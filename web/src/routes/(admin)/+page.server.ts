import { redirect } from '@sveltejs/kit';
import { configuration } from '$lib/server/configuration';

export async function load() {
	const { config, app } = await configuration.read();
	redirect(
		302,
		config.detectors.length > 0 ? '/detections' : app.streams.length ? '/streams' : '/setup'
	);
}

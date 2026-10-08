import { redirect } from '@sveltejs/kit';
import { configuration } from '$lib/server/configuration';
import { managedDetector } from '$lib/server/detector-service';

export async function load() {
	const { config, app } = await configuration.read();
	if (!app.streams.length) redirect(302, '/setup');
	// Guided setup ends by starting monitoring. Until that has happened, reopening the app
	// resumes it. A separately managed detector cannot be started here, so saving is the end.
	const finished = app.streams.some((camera) => camera.setup?.completedAt);
	if (!finished && managedDetector()?.status().phase === 'stopped') redirect(302, '/setup');
	redirect(302, config.detectors.length ? '/detections' : '/streams');
}

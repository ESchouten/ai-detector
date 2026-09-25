import { redirect } from '@sveltejs/kit';
import { configuration } from '$lib/server/configuration';
import { cameraSetupStatus } from '$lib/server/configuration/camera-setup';

export async function load() {
	const document = await configuration.read();
	const { config, app } = document;
	if (config.detectors.length) redirect(302, '/detections');
	const viewingReady =
		app.streams.length > 0 &&
		app.streams.every((camera) => cameraSetupStatus(document, camera.id!).completedAt);
	redirect(302, viewingReady ? '/streams' : '/setup');
}

import { error, type RequestHandler } from '@sveltejs/kit';
import path from 'node:path';
import { DATA_DIRECTORY } from '$lib/server/application-paths';
import { configuration } from '$lib/server/configuration';
import { createCameraOverlayStream, livePreviewRules } from '$lib/server/live-preview';
import { sourceKey } from '$lib/server/source-key';

export const GET: RequestHandler = async ({ url, request }) => {
	const { app, config } = await configuration.read();
	const ids = new Set(url.searchParams.getAll('camera'));
	const cameras = app.streams
		.filter((camera) => camera.id && ids.has(camera.id))
		.map((camera) => ({
			id: camera.id!,
			sourceKey: sourceKey(camera.source, DATA_DIRECTORY),
			rules: livePreviewRules(camera.source, config, app)
		}));
	if (!cameras.length) error(404, 'Camera not found.');
	return new Response(
		createCameraOverlayStream(path.join(DATA_DIRECTORY, 'live'), cameras, request.signal),
		{
			headers: {
				'Content-Type': 'text/event-stream',
				'Cache-Control': 'no-store',
				'X-Accel-Buffering': 'no'
			}
		}
	);
};

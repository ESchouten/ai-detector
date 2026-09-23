import { error, type RequestHandler } from '@sveltejs/kit';
import path from 'node:path';
import { DATA_DIRECTORY } from '$lib/server/application-paths';
import { configuration } from '$lib/server/configuration';
import { createLivePreviewStream, liveSourceKey } from '$lib/server/live-preview';

export const GET: RequestHandler = async ({ params, request }) => {
	const { app, config } = await configuration.read();
	const camera = app.streams.find((camera) => camera.id === params.id);
	if (!camera) error(404, 'Camera not found.');
	const rules = config.detectors.flatMap((rule, index) =>
		rule.detection.source.includes(camera.source)
			? [
					{
						id: `detector-${index + 1}`,
						label: app.detectors[index].label,
						interval: rule.detection.interval ?? 1
					}
				]
			: []
	);
	if (!rules.length) error(409, 'Choose a monitoring rule before opening live detections.');
	return new Response(
		createLivePreviewStream(
			path.join(DATA_DIRECTORY, 'live'),
			liveSourceKey(camera.source, DATA_DIRECTORY),
			rules,
			request.signal
		),
		{
			headers: {
				'Content-Type': 'text/event-stream',
				'Cache-Control': 'no-store',
				'X-Accel-Buffering': 'no'
			}
		}
	);
};

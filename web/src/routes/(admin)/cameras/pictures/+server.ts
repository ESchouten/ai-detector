import { error, type RequestHandler } from '@sveltejs/kit';
import { configuration } from '$lib/server/configuration';
import { createPictureStream } from '$lib/server/camera-pictures';
import { getFfmpegPathWithFallback } from '$lib/server/ffmpeg';
import { previews } from '$lib/server/preview-pool';

export const GET: RequestHandler = async ({ url, request }) => {
	const { app } = await configuration.read();
	const ids = new Set(url.searchParams.getAll('camera'));
	const cameras = app.streams
		.filter((camera) => camera.id && ids.has(camera.id))
		.map((camera) => ({ id: camera.id!, source: camera.source }));
	if (!cameras.length) error(404, 'Camera not found.');
	const executable = await getFfmpegPathWithFallback();
	if (!executable)
		error(503, 'Camera preview software is unavailable. Repair or reinstall AI Detector.');
	return new Response(
		createPictureStream(
			cameras,
			(source, signal) => previews.open(source, executable, signal),
			request.signal
		),
		{
			headers: {
				'Content-Type': 'application/octet-stream',
				'Cache-Control': 'no-store',
				'X-Accel-Buffering': 'no'
			}
		}
	);
};

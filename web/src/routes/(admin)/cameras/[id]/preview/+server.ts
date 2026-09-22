import { error, type RequestHandler } from '@sveltejs/kit';
import { configuration } from '$lib/server/configuration';
import { getFfmpegPathWithFallback } from '$lib/server/ffmpeg';
import { createPreviewStream, MJPEG_BOUNDARY } from '$lib/server/stream-preview';

export const GET: RequestHandler = async ({ params, request }) => {
	const { app } = await configuration.read();
	const camera = app.streams.find((camera) => camera.id === params.id);
	if (!camera) error(404, 'Camera not found.');
	const executable = await getFfmpegPathWithFallback();
	if (!executable)
		error(503, 'Camera preview software is unavailable. Repair or reinstall AI Detector.');
	return new Response(createPreviewStream(camera.source, executable, request.signal), {
		headers: {
			'Content-Type': `multipart/x-mixed-replace; boundary=${MJPEG_BOUNDARY}`,
			'Cache-Control': 'no-store',
			'X-Accel-Buffering': 'no'
		}
	});
};

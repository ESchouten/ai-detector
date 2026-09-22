import path from 'node:path';
import { error, type RequestHandler } from '@sveltejs/kit';
import { getExecutableName, getFfmpegPathWithFallback, isRtspSource } from '$lib/server/ffmpeg';
import { createPreviewStream, MJPEG_BOUNDARY } from '$lib/server/stream-preview';

export const GET: RequestHandler = async ({ params, request }) => {
	const source = params.source?.trim();
	if (!source || !isRtspSource(source)) {
		throw error(400, 'Only RTSP and RTSPS sources are supported for live preview.');
	}

	const ffmpegPath = await getFfmpegPathWithFallback();
	if (!ffmpegPath) {
		throw error(
			500,
			`FFmpeg binary not available. Set FFMPEG_PATH, install ffmpeg in PATH, or place ${getExecutableName()} next to ${path.basename(process.execPath)}.`
		);
	}

	return new Response(createPreviewStream(source, ffmpegPath, request.signal), {
		headers: {
			'Content-Type': `multipart/x-mixed-replace; boundary=${MJPEG_BOUNDARY}`,
			'Cache-Control': 'no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0',
			Pragma: 'no-cache',
			Connection: 'keep-alive',
			'X-Accel-Buffering': 'no'
		}
	});
};

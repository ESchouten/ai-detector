import { json, type RequestHandler } from '@sveltejs/kit';
import * as v from 'valibot';
import { ConfigurationError } from '$lib/configuration';
import { cameraChecks, connectCamera, CameraConnectionError } from '$lib/server/cameras';
import { verifyCameraArchive } from '$lib/server/cameras/archive-check';
import { configuration } from '$lib/server/configuration';
import { cameraArchiveSelection } from '$lib/server/configuration/camera-setup';
import { DATA_DIRECTORY } from '$lib/server/application-paths';
import { getFfmpegPathWithFallback } from '$lib/server/ffmpeg';

const inputSchema = v.object({ checkId: v.optional(v.string()) });

export const POST: RequestHandler = async ({ request, params, url }) => {
	if (request.headers.get('origin') !== url.origin)
		return json(
			{ message: 'Open AI Detector again before checking the recording location.' },
			{ status: 403 }
		);
	try {
		const input = v.safeParse(inputSchema, await request.json());
		if (!input.success)
			return json({ message: 'The recording check request was not valid.' }, { status: 400 });
		const { camera, categories, signature } = cameraArchiveSelection(
			await configuration.read(),
			params.id!
		);
		if (!categories.length)
			throw new CameraConnectionError('This camera has no local recording destination to check.');
		const executable = await getFfmpegPathWithFallback();
		if (!executable)
			throw new CameraConnectionError(
				'Camera software is missing. Repair or reinstall AI Detector.'
			);
		let checkId = input.output.checkId;
		if (checkId) cameraChecks.assert(checkId, camera.source);
		else {
			const result = await connectCamera(
				{ address: '', username: '', password: '', streamUri: camera.source },
				request.signal
			);
			checkId = result.checkId;
		}
		const clip = cameraChecks.file(checkId, 'recording.mp4');
		if (!clip)
			throw new CameraConnectionError(
				'Check the camera picture again. The test recording has expired.'
			);
		await verifyCameraArchive(
			DATA_DIRECTORY,
			params.id!,
			clip,
			categories,
			executable,
			request.signal
		);
		request.signal.throwIfAborted();
		const verifiedAt = new Date().toISOString();
		await configuration.recordArchiveCheck(params.id!, signature, verifiedAt);
		return json({ verifiedAt }, { headers: { 'Cache-Control': 'no-store' } });
	} catch (cause) {
		if (request.signal.aborted) return new Response(null, { status: 499 });
		if (cause instanceof ConfigurationError)
			return json({ message: cause.message }, { status: 400 });
		if (cause instanceof SyntaxError)
			return json({ message: 'The recording check request was not valid.' }, { status: 400 });
		throw cause;
	}
};

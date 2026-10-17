import type { RequestHandler } from './$types';
import { cameraChecks } from '$lib/server/cameras';
import { fileMedia } from '$lib/server/file-media';

export const GET: RequestHandler = async ({ params, request }) => {
	const file = cameraChecks.file(params.id, 'picture.jpg');
	if (!file)
		return new Response('This camera check has expired. Check the camera again.', { status: 404 });
	const response = await fileMedia(file, request, 'image/jpeg');
	response.headers.set('Cache-Control', 'no-store');
	return response;
};

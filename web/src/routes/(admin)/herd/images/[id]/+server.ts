import { herd } from '$lib/server/herd';
import { fileMedia } from '$lib/server/file-media';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = async ({ params, request }) => {
	const file = herd.image(params.id);
	if (!file) return new Response('Not found', { status: 404 });
	return fileMedia(file, request, 'image/jpeg');
};

export const HEAD = GET;

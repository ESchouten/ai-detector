import { error } from '@sveltejs/kit';
import { fileMedia } from '$lib/server/file-media';
import { individuals } from '$lib/server/individuals';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = ({ params, request }) => {
	const file = individuals.picture(params.sighting, params.picture);
	if (!file) error(404, 'Picture not found.');
	return fileMedia(file, request, 'image/jpeg');
};

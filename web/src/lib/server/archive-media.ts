import path from 'node:path';
import { archivePath, ArchivePathError, isMissingFile } from './archive.ts';
import { fileMedia } from './file-media.ts';
import { STAGES } from '../schema.ts';

const CONTENT_TYPES: Record<string, string> = {
	'.jpg': 'image/jpeg',
	'.jpeg': 'image/jpeg',
	'.png': 'image/png',
	'.gif': 'image/gif',
	'.webp': 'image/webp',
	'.bmp': 'image/bmp',
	'.mp4': 'video/mp4',
	'.webm': 'video/webm',
	'.mov': 'video/quicktime',
	'.json': 'application/json'
};

export async function archiveMedia(
	directory: string,
	location: { category: string; stage: string; timestamp: string; resource: string },
	request: Request
): Promise<Response> {
	const { category, stage, timestamp, resource } = location;
	const contentType = CONTENT_TYPES[path.extname(resource).toLowerCase()];
	if (!STAGES.some((value) => value === stage) || !contentType)
		return new Response('Not found', { status: 404 });
	try {
		return await fileMedia(
			await archivePath(directory, category, stage, timestamp, resource),
			request,
			contentType
		);
	} catch (error) {
		if (error instanceof ArchivePathError || isMissingFile(error))
			return new Response('Not found', { status: 404 });
		throw error;
	}
}

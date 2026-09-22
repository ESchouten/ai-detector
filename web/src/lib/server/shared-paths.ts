import path from 'node:path';
export { CONFIG_PATH, APP_CONFIG_PATH, DETECTIONS_DIR } from './application-paths';

export function resolveWithinDirectory(
	directoryPath: string,
	requestedPath: string
): string | null {
	const normalizedPath = requestedPath.replaceAll('\\', '/').replace(/^\/+/, '');
	const resolvedPath = path.resolve(directoryPath, normalizedPath);
	const relativePath = path.relative(directoryPath, resolvedPath);

	if (
		relativePath === '..' ||
		relativePath.startsWith(`..${path.sep}`) ||
		path.isAbsolute(relativePath)
	) {
		return null;
	}

	return resolvedPath;
}

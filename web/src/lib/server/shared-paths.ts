import path from 'node:path';
import type { AppConfig, Config } from '$lib/schema';
import { CONFIG_PATH, APP_CONFIG_PATH } from './application-paths';
import { writeJson } from './json-file';
import { managedDetector } from './detector-service';
export { CONFIG_PATH, APP_CONFIG_PATH, DETECTIONS_DIR } from './application-paths';

export function resolveWithinDirectory(
	directoryPath: string,
	requestedPath: string
): string | null {
	const normalizedPath = requestedPath.replaceAll('\\', '/').replace(/^\/+/, '');
	const resolvedPath = path.resolve(directoryPath, normalizedPath);
	const relativePath = path.relative(directoryPath, resolvedPath);

	if (relativePath.startsWith('..') || path.isAbsolute(relativePath)) {
		return null;
	}

	return resolvedPath;
}

export const saveConfig = async ({ config, app }: { config: Config; app: AppConfig }) => {
	const detector = managedDetector();
	if (config.detectors.length > 0) await detector?.validate(config);
	await writeJson(APP_CONFIG_PATH, app);
	await writeJson(CONFIG_PATH, config);
	if (config.detectors.length === 0) await detector?.stop();
	else await detector?.apply();
};

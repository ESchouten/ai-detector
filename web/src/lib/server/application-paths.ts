import { dev } from '$app/environment';
import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import path from 'node:path';

declare const __AI_DETECTOR_WEB_TARGET__: string;

export const EXECUTABLE_DIRECTORY = path.dirname(process.execPath);
export const PACKAGED = !dev && __AI_DETECTOR_WEB_TARGET__ !== 'node';

function dataDirectory(): string {
	if (process.env.AIDETECTOR_DATA_DIR) return path.resolve(process.env.AIDETECTOR_DATA_DIR);
	if (!PACKAGED) return process.cwd();
	// Continue to read existing portable installations in their original location.
	if (existsSync(path.join(EXECUTABLE_DIRECTORY, 'config.json'))) return EXECUTABLE_DIRECTORY;
	if (process.platform === 'win32') {
		return path.join(
			process.env.LOCALAPPDATA ?? path.join(homedir(), 'AppData', 'Local'),
			'AI Detector'
		);
	}
	if (process.platform === 'darwin')
		return path.join(homedir(), 'Library', 'Application Support', 'AI Detector');
	return path.join(
		process.env.XDG_DATA_HOME ?? path.join(homedir(), '.local', 'share'),
		'ai-detector'
	);
}

export const DATA_DIRECTORY = dataDirectory();
export const CONFIG_PATH = path.join(DATA_DIRECTORY, 'config.json');
export const APP_CONFIG_PATH = path.join(DATA_DIRECTORY, 'app.json');
export const DETECTIONS_DIR = path.join(DATA_DIRECTORY, 'detections');

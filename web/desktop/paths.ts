import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import path from 'node:path';

/** Shared by the executable bootstrap and the web application's file stores. */
export function dataDirectory(packaged: boolean): string {
	if (process.env.AIDETECTOR_DATA_DIR) return path.resolve(process.env.AIDETECTOR_DATA_DIR);
	if (!packaged) return process.cwd();
	const executable = path.dirname(process.execPath);
	if (existsSync(path.join(executable, 'config.json'))) return executable;
	if (process.platform === 'win32')
		return path.join(
			process.env.LOCALAPPDATA ?? path.join(homedir(), 'AppData', 'Local'),
			'AI Detector'
		);
	if (process.platform === 'darwin')
		return path.join(homedir(), 'Library', 'Application Support', 'AI Detector');
	return path.join(
		process.env.XDG_DATA_HOME ?? path.join(homedir(), '.local', 'share'),
		'ai-detector'
	);
}

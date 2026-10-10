import assert from 'node:assert/strict';
import { test } from 'node:test';
import path from 'node:path';
import { homedir } from 'node:os';
import { dataDirectory } from './paths.ts';

test('an explicit data directory has the same meaning in desktop and server builds', (t) => {
	const previous = process.env.AIDETECTOR_DATA_DIR;
	t.after(() => {
		if (previous === undefined) delete process.env.AIDETECTOR_DATA_DIR;
		else process.env.AIDETECTOR_DATA_DIR = previous;
	});
	process.env.AIDETECTOR_DATA_DIR = 'sample-data';
	assert.equal(dataDirectory(true), path.resolve('sample-data'));
	assert.equal(dataDirectory(false), path.resolve('sample-data'));
	delete process.env.AIDETECTOR_DATA_DIR;
	assert.equal(dataDirectory(false), process.cwd());
	const installed =
		process.platform === 'darwin'
			? path.join(homedir(), 'Library', 'Application Support', 'AI Detector')
			: process.platform === 'win32'
				? path.join(
						process.env.LOCALAPPDATA ?? path.join(homedir(), 'AppData', 'Local'),
						'AI Detector'
					)
				: path.join(
						process.env.XDG_DATA_HOME ?? path.join(homedir(), '.local', 'share'),
						'ai-detector'
					);
	assert.equal(dataDirectory(true), installed);
});

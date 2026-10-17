import assert from 'node:assert/strict';
import { test } from 'node:test';
import path from 'node:path';
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
});

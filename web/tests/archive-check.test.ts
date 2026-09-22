import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdir, mkdtemp, readFile, readdir, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test, type TestContext } from 'node:test';
import { promisify } from 'node:util';
import ffmpeg from 'ffmpeg-static';
import { DetectionArchive } from '../src/lib/server/archive.ts';
import { verifyCameraArchive } from '../src/lib/server/cameras/archive-check.ts';

const execute = promisify(execFile);

async function fixture(t: TestContext) {
	assert.ok(ffmpeg);
	const directory = await mkdtemp(path.join(tmpdir(), 'ai-archive-check-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	const clip = path.join(directory, 'camera.mp4');
	await execute(ffmpeg, [
		'-hide_banner',
		'-loglevel',
		'error',
		'-f',
		'lavfi',
		'-i',
		'testsrc2=size=160x120:rate=4',
		'-t',
		'1',
		'-c:v',
		'libx264',
		'-pix_fmt',
		'yuv420p',
		clip
	]);
	return { directory, clip, executable: ffmpeg };
}

test('archive check saves and decodes in every destination without creating detection events', async (t) => {
	const { directory, clip, executable } = await fixture(t);
	const original = await readFile(clip);
	await verifyCameraArchive(
		directory,
		'camera-one',
		clip,
		['calving', 'yard', 'calving', ''],
		executable
	);
	for (const category of ['calving', 'yard'])
		assert.deepEqual(await readdir(path.join(directory, 'detections', category)), []);
	assert.deepEqual(await readFile(clip), original);
	const archive = new DetectionArchive(path.join(directory, 'detections'));
	assert.deepEqual(await archive.types(), ['calving', 'yard']);
	assert.deepEqual(await readdir(path.join(directory, 'detections')), ['calving', 'yard']);
	assert.deepEqual(await archive.page({ offset: 0, limit: 10 }), {
		items: [],
		nextOffset: 0,
		hasMore: false
	});
});

test('archive check rejects unreadable video and removes the incomplete test', async (t) => {
	const { directory, clip, executable } = await fixture(t);
	await writeFile(clip, 'not a video');
	await assert.rejects(
		verifyCameraArchive(directory, 'camera-one', clip, ['calving'], executable),
		/could not be played/
	);
	assert.deepEqual(await readdir(path.join(directory, 'detections/calving')), []);
});

test('archive check rejects traversal and linked output folders without writing through them', async (t) => {
	const { directory, clip, executable } = await fixture(t);
	await assert.rejects(
		verifyCameraArchive(directory, 'camera-one', clip, ['../outside'], executable),
		/location is invalid/
	);
	const outside = path.join(directory, 'outside');
	await mkdir(outside);
	await mkdir(path.join(directory, 'detections'));
	await symlink(outside, path.join(directory, 'detections/calving'), 'junction');
	await assert.rejects(
		verifyCameraArchive(directory, 'camera-one', clip, ['calving'], executable),
		/linked folder/
	);
	assert.deepEqual(await readdir(outside), []);
});

test('archive check reports an occupied destination and honors cancellation', async (t) => {
	const { directory, clip, executable } = await fixture(t);
	await mkdir(path.join(directory, 'detections'));
	await writeFile(path.join(directory, 'detections/calving'), 'existing file');
	await assert.rejects(
		verifyCameraArchive(directory, 'camera-one', clip, ['calving'], executable),
		/contains a file/
	);
	const controller = new AbortController();
	controller.abort();
	await assert.rejects(
		verifyCameraArchive(directory, 'camera-one', clip, ['yard'], executable, controller.signal),
		{ name: 'AbortError' }
	);
	assert.deepEqual(await readdir(path.join(directory, 'detections')), ['calving']);
});

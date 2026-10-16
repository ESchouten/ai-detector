import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import type { TestContext } from 'node:test';
import { promisify } from 'node:util';
import ffmpeg from 'ffmpeg-static';

/** A folder of its own for one test, removed after it. */
export async function temporaryDirectory(t: TestContext, prefix: string) {
	const directory = await mkdtemp(path.join(tmpdir(), prefix));
	t.after(() => rm(directory, { recursive: true, force: true }));
	return directory;
}

/** What the detector writes in the metadata.json of a recording it validated. */
export function recordingMetadata(timestamp: string) {
	return {
		timestamp,
		validated: true,
		confidence: 0.9,
		confidences: { cow: 0.9 },
		detections: 1,
		start: '2026-09-22T10:00:00',
		end: '2026-09-22T10:00:02',
		duration: 2
	};
}

/** Writes three seconds of video, as a camera in a test streams it, and returns its path. */
export async function sampleClip(directory: string) {
	assert.ok(ffmpeg);
	const clip = path.join(directory, 'sample.mp4');
	await promisify(execFile)(ffmpeg, [
		'-hide_banner',
		'-loglevel',
		'error',
		'-f',
		'lavfi',
		'-i',
		'testsrc2=size=320x240:rate=12',
		'-t',
		'3',
		'-c:v',
		'libx264',
		'-pix_fmt',
		'yuv420p',
		'-movflags',
		'+faststart',
		clip
	]);
	return clip;
}

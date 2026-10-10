import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, readdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test, type TestContext } from 'node:test';
import { setTimeout as delay } from 'node:timers/promises';
import writeFileAtomic from 'write-file-atomic';
import {
	createCameraOverlayStream,
	type LivePreviewCamera
} from '../src/lib/server/live-preview.ts';
import { sourceKey as keyOf } from '../src/lib/server/source-key.ts';

const rules = [
	{ id: 'detector-1', label: 'People', preset: 'people', interval: 1 },
	{ id: 'detector-2', label: 'Vehicles', interval: 1 }
];
const sourceKey = keyOf('rtsp://user:secret@camera/live', '/data');
const box = { x1: 1, y1: 2, x2: 10, y2: 12, label: 'cow', confidence: 0.9, trackId: 17 };

async function fixture(t: TestContext) {
	const directory = await mkdtemp(path.join(tmpdir(), 'detector-live-'));
	await mkdir(path.join(directory, 'frames'));
	const readers: ReadableStreamDefaultReader<Uint8Array>[] = [];
	t.after(async () => {
		for (const reader of readers) await reader.cancel();
		// A stream that closed by itself may still be removing its lease; Windows refuses
		// a second removal of that file until the first has finished.
		await rm(directory, { recursive: true, force: true, maxRetries: 10, retryDelay: 50 });
	});
	const session = async (runId = 'run-1', updatedAt = new Date().toISOString()) => {
		await writeFileAtomic(
			path.join(directory, 'session.json'),
			JSON.stringify({ version: 1, runId, updatedAt })
		);
	};
	const frame = async (ruleId: string, changes = {}, key = sourceKey) => {
		await writeFileAtomic(
			path.join(directory, 'frames', `${key}.${ruleId}.json`),
			JSON.stringify({
				version: 1,
				runId: 'run-1',
				sourceKey: key,
				ruleId,
				publishedAt: new Date().toISOString(),
				image: { width: 24, height: 16 },
				boxes: [box],
				...changes
			})
		);
	};
	const open = (cameras: LivePreviewCamera[] = [{ id: 'shed', sourceKey, rules }]) => {
		const abort = new AbortController();
		const stream = createCameraOverlayStream(directory, cameras, abort.signal);
		const reader = stream.getReader();
		readers.push(reader);
		return { reader, abort };
	};
	const lease = path.join(directory, 'leases', `${sourceKey}.json`);
	return { directory, session, frame, open, lease };
}

/** The event that clears the boxes of one rule on the camera `shed`. */
function status(ruleId: string): string {
	return `event: status\ndata: {"ruleId":"${ruleId}","cameraId":"shed"}\n\n`;
}

async function chunk(reader: ReadableStreamDefaultReader<Uint8Array>): Promise<string> {
	const result = await reader.read();
	assert.equal(result.done, false, 'Preview closed unexpectedly');
	return new TextDecoder().decode(result.value);
}

async function nextUpdate(reader: ReadableStreamDefaultReader<Uint8Array>): Promise<string> {
	// A poll already in flight can queue a heartbeat before a fixture changes.
	let output: string;
	do {
		output = await chunk(reader);
	} while (output.startsWith('event: heartbeat\n'));
	return output;
}

async function closed(reader: ReadableStreamDefaultReader<Uint8Array>): Promise<void> {
	while (true) {
		const result = await reader.read();
		if (result.done) return;
		assert.match(new TextDecoder().decode(result.value), /^event: heartbeat\n/);
	}
}

async function until(read: () => Promise<boolean>): Promise<void> {
	const deadline = Date.now() + 3000;
	while (Date.now() < deadline) {
		if (await read()) return;
		await delay(20);
	}
	assert.fail('Preview state did not progress');
}

test(
	'one camera preserves every rule, image coordinates and tracking IDs without exposing source credentials',
	{ timeout: 5000 },
	async (t) => {
		const { session, frame, open, lease } = await fixture(t);
		await session();
		await frame('detector-1');
		await frame('detector-2');
		const { reader } = open();
		const output = await chunk(reader);
		const frames = output
			.split('\n')
			.filter((line) => line.startsWith('data: '))
			.map((line) => JSON.parse(line.slice(6)));
		assert.deepEqual(
			frames.map((frame) => frame.ruleLabel),
			['People', 'Vehicles']
		);
		assert.equal(frames[0].boxes[0].trackId, 17);
		assert.equal(frames[0].rulePreset, 'people');
		assert.equal(frames[0].image.width, 24);
		assert.ok(!output.includes('secret'));
		await until(
			async () =>
				JSON.parse(await readFile(lease, 'utf8').catch(() => '{}')).expiresAt > Date.now() / 1000
		);
		await reader.cancel();
		await assert.rejects(readFile(lease), { code: 'ENOENT' });
	}
);

test(
	'multiple viewers share their lease and reader cancellation cleans the last lease',
	{ timeout: 5000 },
	async (t) => {
		const { open, lease } = await fixture(t);
		const first = open();
		const second = open();
		assert.equal(await chunk(first.reader), status('detector-1') + status('detector-2'));
		await chunk(second.reader);
		await until(
			async () => JSON.parse(await readFile(lease, 'utf8').catch(() => '{}')).version === 1
		);
		await first.reader.cancel();
		assert.equal(JSON.parse(await readFile(lease, 'utf8')).version, 1);
		await second.reader.cancel();
		await assert.rejects(readFile(lease), { code: 'ENOENT' });
	}
);

test(
	'an aborted HTTP request removes its lease and a simultaneous new viewer retains one',
	{ timeout: 5000 },
	async (t) => {
		const { open, lease } = await fixture(t);
		const first = open();
		await chunk(first.reader);
		first.abort.abort();
		const replacement = open();
		await chunk(replacement.reader);
		await until(
			async () =>
				JSON.parse(await readFile(lease, 'utf8').catch(() => '{}')).expiresAt > Date.now() / 1000
		);
		await closed(first.reader);
		await replacement.reader.cancel();
		await assert.rejects(readFile(lease), { code: 'ENOENT' });
	}
);

test(
	'a formerly fresh frame expires independently per rule; unchanged streams send a heartbeat',
	{ timeout: 5000 },
	async (t) => {
		const { session, frame, open } = await fixture(t);
		await session();
		await frame('detector-1');
		await frame('detector-2');
		const { reader } = open();
		assert.match(await chunk(reader), /event: frame/);
		assert.match(await chunk(reader), /event: heartbeat/);
		await frame('detector-1', { publishedAt: new Date(Date.now() - 16000).toISOString() });
		assert.equal(await nextUpdate(reader), status('detector-1'));
	}
);

test(
	'a stopped detector clears its formerly fresh pictures and a different run closes for a configuration reload',
	{ timeout: 5000 },
	async (t) => {
		const { directory, session, frame, open } = await fixture(t);
		await session();
		await frame('detector-1');
		const { reader } = open();
		assert.match(await chunk(reader), /event: frame/);
		await rm(path.join(directory, 'session.json'));
		assert.equal(await nextUpdate(reader), status('detector-1'));
		await session('run-2');
		await closed(reader);
	}
);

test(
	'old-run and malformed records are never shown as current results',
	{ timeout: 5000 },
	async (t) => {
		const { directory, session, frame, open } = await fixture(t);
		await session();
		await frame('detector-1', { runId: 'previous-run' });
		await frame('detector-2', { image: null });
		const { reader } = open();
		assert.equal(await chunk(reader), status('detector-1') + status('detector-2'));
		await reader.cancel();
		assert.equal((await readdir(path.join(directory, 'leases'))).length, 0);
	}
);

test(
	'a slow reader skips intermediate pictures and receives the newest available record',
	{ timeout: 5000 },
	async (t) => {
		const { session, frame, open } = await fixture(t);
		await session();
		await frame('detector-1');
		const { reader } = open();
		await delay(700);
		await frame('detector-1', { boxes: [{ ...box, label: 'intermediate' }] });
		await delay(700);
		await frame('detector-1', { boxes: [{ ...box, label: 'newest' }] });
		assert.ok(!(await chunk(reader)).includes('intermediate'));
		assert.match(await nextUpdate(reader), /newest/);
	}
);

test('local paths share the detector source hash while camera URLs and numeric sources stay literal', () => {
	assert.equal(keyOf('video.mp4', '/data'), keyOf('/data/video.mp4', '/elsewhere'));
	assert.equal(keyOf('0', '/data'), keyOf('0', '/elsewhere'));
	assert.equal(keyOf('rtsp://camera/live', '/data'), keyOf('rtsp://camera/live', '/elsewhere'));
});

test(
	'a stale process heartbeat suppresses even recently published pictures',
	{ timeout: 5000 },
	async (t) => {
		const { session, frame, open } = await fixture(t);
		await session('run-1', new Date(Date.now() - 7000).toISOString());
		await frame('detector-1');
		const { reader } = open();
		assert.equal(await chunk(reader), status('detector-1') + status('detector-2'));
	}
);

test(
	'camera overlays multiplex cameras and rules, and a stale frame clears only its own camera',
	{ timeout: 5000 },
	async (t) => {
		const { directory, session, frame, open } = await fixture(t);
		const otherKey = keyOf('rtsp://other-camera/live', '/data');
		const cameras = [
			{ id: 'shed', sourceKey, rules },
			{ id: 'pen', sourceKey: otherKey, rules: [rules[0]] }
		];
		await session();
		await frame('detector-1');
		await frame('detector-2');
		await frame('detector-1', { boxes: [] }, otherKey);
		const { reader, abort } = open(cameras);
		const output = await chunk(reader);
		const frames = output
			.split('\n')
			.filter((line) => line.startsWith('data: '))
			.map((line) => JSON.parse(line.slice(6)));
		assert.deepEqual(
			frames.map(({ cameraId, ruleId }) => [cameraId, ruleId]),
			[
				['shed', 'detector-1'],
				['shed', 'detector-2'],
				['pen', 'detector-1']
			]
		);
		assert.deepEqual(frames[0].image, { width: 24, height: 16 });
		assert.equal(frames[0].boxes[0].label, 'cow');
		assert.equal(frames[0].rulePreset, 'people');
		assert.deepEqual(frames[2].boxes, []);
		assert.ok(!output.includes('secret'));
		await until(async () => (await readdir(path.join(directory, 'leases'))).length === 2);
		await frame('detector-1', { publishedAt: new Date(Date.now() - 16000).toISOString() });
		const stale = await nextUpdate(reader);
		assert.match(stale, /event: status/);
		assert.match(stale, /"cameraId":"shed"/);
		assert.ok(!stale.includes('"cameraId":"pen"'));
		abort.abort();
		await closed(reader);
		await until(async () => (await readdir(path.join(directory, 'leases'))).length === 0);
	}
);

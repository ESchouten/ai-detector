import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test, type TestContext } from 'node:test';
import { setTimeout as delay } from 'node:timers/promises';
import { createLivePreviewStream, liveSourceKey } from '../src/lib/server/live-preview.ts';

const rules = [
	{ id: 'detector-1', label: 'People', interval: 1 },
	{ id: 'detector-2', label: 'Vehicles', interval: 1 }
];
const sourceKey = liveSourceKey('rtsp://user:secret@camera/live', '/data');

async function fixture(t: TestContext) {
	const directory = await mkdtemp(path.join(tmpdir(), 'detector-live-'));
	await mkdir(path.join(directory, 'frames'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	const session = async (runId = 'run-1', updatedAt = new Date().toISOString()) => {
		await writeFile(
			path.join(directory, 'session.json'),
			JSON.stringify({ version: 1, runId, updatedAt })
		);
	};
	const frame = async (ruleId: string, changes = {}) => {
		await writeFile(
			path.join(directory, 'frames', `${sourceKey}.${ruleId}.json`),
			JSON.stringify({
				version: 1,
				runId: 'run-1',
				sourceKey,
				ruleId,
				capturedAt: '2020-01-01T00:00:00',
				publishedAt: new Date().toISOString(),
				image: { width: 24, height: 16, jpeg: Buffer.from('encoded-image').toString('base64') },
				boxes: [{ x1: 1, y1: 2, x2: 10, y2: 12, label: 'cow', confidence: 0.9, trackId: 17 }],
				...changes
			})
		);
	};
	const open = () => {
		const abort = new AbortController();
		const reader = createLivePreviewStream(directory, sourceKey, rules, abort.signal).getReader();
		t.after(async () => {
			abort.abort();
			await reader.cancel();
		});
		return { reader, abort };
	};
	const lease = path.join(directory, 'leases', `${sourceKey}.json`);
	return { directory, session, frame, open, lease };
}

async function chunk(reader: ReadableStreamDefaultReader<Uint8Array>): Promise<string> {
	const result = await reader.read();
	assert.equal(result.done, false, 'Preview closed unexpectedly');
	return new TextDecoder().decode(result.value);
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
		assert.match(await chunk(first.reader), /Waiting for the detector/);
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
		assert.equal((await first.reader.read()).done, true);
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
		const stale = await chunk(reader);
		assert.match(stale, /No recent analyzed picture/);
		assert.match(stale, /People/);
		assert.ok(!stale.includes('Vehicles'));
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
		assert.match(await chunk(reader), /no longer publishing/);
		await session('run-2');
		assert.equal((await reader.read()).done, true);
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
		const output = await chunk(reader);
		assert.match(output, /current detector run/);
		assert.match(output, /could not be read/);
		assert.ok(!output.includes('event: frame'));
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
		await frame('detector-1', { image: { width: 24, height: 16, jpeg: 'intermediate' } });
		await delay(700);
		await frame('detector-1', { image: { width: 24, height: 16, jpeg: 'newest' } });
		assert.ok(!(await chunk(reader)).includes('intermediate'));
		assert.match(await chunk(reader), /newest/);
	}
);

test('local paths share the detector source hash while camera URLs and numeric sources stay literal', () => {
	assert.equal(liveSourceKey('video.mp4', '/data'), liveSourceKey('/data/video.mp4', '/elsewhere'));
	assert.equal(liveSourceKey('0', '/data'), liveSourceKey('0', '/elsewhere'));
	assert.equal(
		liveSourceKey('rtsp://camera/live', '/data'),
		liveSourceKey('rtsp://camera/live', '/elsewhere')
	);
});

test(
	'a stale process heartbeat suppresses even recently published pictures',
	{ timeout: 5000 },
	async (t) => {
		const { session, frame, open } = await fixture(t);
		await session('run-1', new Date(Date.now() - 7000).toISOString());
		await frame('detector-1');
		const { reader } = open();
		const output = await chunk(reader);
		assert.match(output, /no longer publishing/);
		assert.ok(!output.includes('event: frame'));
	}
);

import assert from 'node:assert/strict';
import {
	mkdtemp,
	mkdir,
	open,
	rm,
	symlink,
	truncate,
	writeFile,
	type FileHandle
} from 'node:fs/promises';
import { once, type EventEmitter } from 'node:events';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test, type TestContext } from 'node:test';
import { DetectionArchive, ArchivePathError } from '../src/lib/server/archive.ts';
import { archiveMedia } from '../src/lib/server/archive-media.ts';
import { detectionKey, mergeDetections } from '../src/lib/detections.ts';

const timestamp = '2026-09-22T10-00-00.000000';
const location = { category: 'cow', stage: 'approved', timestamp, resource: 'video.mp4' };
const metadata = {
	timestamp,
	validated: true,
	confidence: 0.9,
	confidences: { cow: 0.9 },
	detections: 1,
	start: '2026-09-22T10:00:00',
	end: '2026-09-22T10:00:02',
	duration: 2
};

async function fixture(t: TestContext) {
	const directory = await mkdtemp(path.join(tmpdir(), 'ai-archive-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	const root = path.join(directory, 'detections');
	const event = path.join(root, location.category, location.stage, timestamp);
	await mkdir(event, { recursive: true });
	await writeFile(path.join(event, 'metadata.json'), JSON.stringify(metadata));
	await writeFile(path.join(event, 'video.mp4'), '0123456789');
	return { directory, root, event, archive: new DetectionArchive(root) };
}

async function watchArchiveFiles(t: TestContext, file: string): Promise<FileHandle[]> {
	const probe = await open(file);
	const prototype: FileHandle = Object.getPrototypeOf(probe);
	await probe.close();
	const handles: FileHandle[] = [];
	const stat = prototype.stat;
	t.mock.method(prototype, 'stat', function (this: FileHandle) {
		handles.push(this);
		return stat.call(this);
	});
	return handles;
}

test('archive filters, stable pagination and identity include category and stage', async (t) => {
	const { root, archive } = await fixture(t);
	for (const [category, stage] of [
		['sheep', 'approved'],
		['cow', 'rejected']
	]) {
		const folder = path.join(root, category, stage, timestamp);
		await mkdir(folder, { recursive: true });
		await writeFile(path.join(folder, 'metadata.json'), JSON.stringify(metadata));
	}
	await mkdir(path.join(root, 'cow', '.pending', 'event-in-progress'), { recursive: true });
	assert.deepEqual(await archive.types(), ['cow', 'sheep']);
	const first = await archive.page({ offset: 0, limit: 2 });
	const second = await archive.page({ offset: first.nextOffset, limit: 2 });
	assert.equal(first.hasMore, true);
	assert.equal(second.hasMore, false);
	assert.equal(new Set([...first.items, ...second.items].map(detectionKey)).size, 3);
	assert.deepEqual(
		first.items.map((entry) => entry.stage),
		['approved', 'rejected']
	);
	assert.equal(
		(await archive.page({ type: 'sheep', stage: 'rejected', offset: 0, limit: 10 })).items.length,
		0
	);
});

test('only a missing archive is empty; malformed metadata remains an error', async (t) => {
	const { root, event, archive } = await fixture(t);
	assert.deepEqual(await new DetectionArchive(path.join(root, 'missing')).types(), []);
	await writeFile(path.join(event, 'metadata.json'), '{broken');
	await assert.rejects(archive.page({ offset: 0, limit: 24 }), SyntaxError);
	await writeFile(
		path.join(event, 'metadata.json'),
		JSON.stringify({ ...metadata, duration: 'invalid' })
	);
	await assert.rejects(archive.page({ offset: 0, limit: 24 }), /Invalid archive metadata/);
});

test('publishing a new recording between offset pages does not duplicate displayed detections', async (t) => {
	const { root, archive } = await fixture(t);
	async function record(timestamp: string) {
		const event = path.join(root, 'cow', 'approved', timestamp);
		await mkdir(event, { recursive: true });
		await writeFile(path.join(event, 'metadata.json'), JSON.stringify({ ...metadata, timestamp }));
	}
	const older = ['2026-09-22T09-00-00.000000', '2026-09-22T08-00-00.000000'];
	for (const timestamp of older) await record(timestamp);
	const first = await archive.page({ offset: 0, limit: 2 });
	await record('2026-09-22T11-00-00.000000');
	const second = await archive.page({ offset: first.nextOffset, limit: 2 });
	assert.equal(detectionKey(first.items[1]), detectionKey(second.items[0]));
	const displayed = mergeDetections(first.items, second.items);
	assert.deepEqual(
		displayed.map((entry) => entry.timestamp),
		[timestamp, ...older]
	);
	assert.deepEqual(mergeDetections(displayed, second.items), displayed);
	assert.equal(second.nextOffset, 4);
	assert.equal(second.hasMore, false);
});

test('an already aborted archive request closes its file without creating a broken stream', async (t) => {
	const { root, event } = await fixture(t);
	const files = await watchArchiveFiles(t, path.join(event, 'video.mp4'));
	const reason = new Error('Client disconnected');
	await assert.rejects(
		archiveMedia(
			root,
			location,
			new Request('http://localhost', { signal: AbortSignal.abort(reason) })
		),
		reason
	);
	assert.equal(files.length, 1);
	assert.equal(files[0].fd, -1);
});

for (const cancellation of ['request', 'response'] as const) {
	test(
		`${cancellation} cancellation closes an archive file before the download finishes`,
		{ timeout: 2000 },
		async (t) => {
			const { root, event } = await fixture(t);
			const video = path.join(event, 'video.mp4');
			await truncate(video, 64 * 1024 * 1024);
			const files = await watchArchiveFiles(t, video);
			const abort = new AbortController();
			const response = await archiveMedia(
				root,
				location,
				new Request('http://localhost', { signal: abort.signal })
			);
			assert.equal(files.length, 1);
			// FileHandle is an EventEmitter at runtime; Node 22 typings omit that inheritance.
			const closed = once(files[0] as FileHandle & EventEmitter, 'close');
			if (cancellation === 'request') {
				abort.abort();
				await assert.rejects(response.arrayBuffer(), { name: 'AbortError' });
			} else {
				await response.body!.cancel();
			}
			await closed;
			assert.equal(files[0].fd, -1);
		}
	);
}

test('decoded traversal cannot read outside the archive', async (t) => {
	const { root, archive } = await fixture(t);
	for (const type of ['..', '../secrets', '..\\secrets', '/tmp', 'cow\0']) {
		await assert.rejects(archive.page({ type, offset: 0, limit: 1 }), ArchivePathError);
		const response = await archiveMedia(
			root,
			{ ...location, category: type },
			new Request('http://localhost')
		);
		assert.equal(response.status, 404);
	}
});

test('symbolic links cannot read outside the archive', async (t) => {
	const { directory, root } = await fixture(t);
	await writeFile(path.join(directory, 'secret.json'), '{"secret":true}');
	try {
		await symlink(
			path.join(directory, 'secret.json'),
			path.join(root, 'cow', 'approved', timestamp, 'escape.json'),
			'file'
		);
	} catch (error) {
		if (process.platform === 'win32' && (error as NodeJS.ErrnoException).code === 'EPERM') {
			t.skip('Windows requires Developer Mode or elevated permission to create symbolic links.');
			return;
		}
		throw error;
	}
	assert.equal(
		(
			await archiveMedia(
				root,
				{ ...location, resource: 'escape.json' },
				new Request('http://localhost')
			)
		).status,
		404
	);
});

for (const [range, status, body, contentRange] of [
	[null, 200, '0123456789', null],
	['bytes=2-5', 206, '2345', 'bytes 2-5/10'],
	['bytes=7-', 206, '789', 'bytes 7-9/10'],
	['bytes=-3', 206, '789', 'bytes 7-9/10'],
	['bytes=-99', 206, '0123456789', 'bytes 0-9/10'],
	['bytes=0-0', 206, '0', 'bytes 0-0/10'],
	['bytes=7-99', 206, '789', 'bytes 7-9/10'],
	['bytes=10-', 416, '', 'bytes */10'],
	['bytes=5-2', 416, '', 'bytes */10'],
	['bytes=-0', 416, '', 'bytes */10'],
	['bytes=0-1,4-5', 200, '0123456789', null],
	['bytes=0-1,2-3', 200, '0123456789', null],
	['items=10-', 200, '0123456789', null],
	['bytes=word-3', 200, '0123456789', null],
	['bytes=-', 200, '0123456789', null],
	['invalid', 200, '0123456789', null]
] as const) {
	test(`archive media serves ${range ?? 'a full file'} with status ${status}`, async (t) => {
		const { root } = await fixture(t);
		const response = await archiveMedia(
			root,
			location,
			new Request('http://localhost', { headers: range ? { Range: range } : {} })
		);
		assert.equal(response.status, status);
		assert.equal(response.headers.get('content-range'), contentRange);
		assert.equal(await response.text(), body);
		if (status !== 416) {
			assert.equal(response.headers.get('content-length'), String(body.length));
			assert.equal(response.headers.get('content-type'), 'video/mp4');
		}
	});
}

test('empty media has no satisfiable byte range', async (t) => {
	const { root, event } = await fixture(t);
	await truncate(path.join(event, 'video.mp4'), 0);
	const full = await archiveMedia(root, location, new Request('http://localhost'));
	assert.equal(full.status, 200);
	assert.equal(full.headers.get('content-length'), '0');
	assert.equal(await full.text(), '');
	const partial = await archiveMedia(
		root,
		location,
		new Request('http://localhost', { headers: { Range: 'bytes=0-' } })
	);
	assert.equal(partial.status, 416);
	assert.equal(partial.headers.get('content-range'), 'bytes */0');
});

test('HEAD and conditional ranges do not claim an unsupported partial representation', async (t) => {
	const { root } = await fixture(t);
	const head = await archiveMedia(
		root,
		location,
		new Request('http://localhost', { method: 'HEAD', headers: { Range: 'bytes=2-3' } })
	);
	assert.equal(head.status, 200);
	assert.equal(head.headers.get('content-length'), '10');
	assert.equal(await head.text(), '');
	const conditional = await archiveMedia(
		root,
		location,
		new Request('http://localhost', { headers: { Range: 'bytes=2-3', 'If-Range': 'outdated' } })
	);
	assert.equal(conditional.status, 200);
	assert.equal(await conditional.text(), '0123456789');
});

test('missing media and unsupported resources return 404', async (t) => {
	const { root } = await fixture(t);
	for (const resource of ['absent.jpg', 'injected.svg', '../config.json', '..\\config.json']) {
		assert.equal(
			(await archiveMedia(root, { ...location, resource }, new Request('http://localhost'))).status,
			404
		);
	}
});

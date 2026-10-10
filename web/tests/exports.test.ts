import assert from 'node:assert/strict';
import { ReadStream } from 'node:fs';
import { mkdtemp, mkdir, readFile, rm, symlink, truncate, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test, type TestContext } from 'node:test';
import { setTimeout as delay } from 'node:timers/promises';
import { unzipSync } from 'fflate';
import * as v from 'valibot';
import { recordingExportInput } from '../src/lib/detections.ts';
import { DetectionArchive } from '../src/lib/server/archive.ts';
import { exportRecordings } from '../src/lib/server/recording-export.ts';
import { backupSettings } from '../src/lib/server/settings-backup.ts';
import { zipDownload } from '../src/lib/server/zip-download.ts';
import { ConfigurationStore } from '../src/lib/server/configuration/store.ts';
import { InstallationImport } from '../src/lib/server/installation-import/service.ts';
import { settingsStore } from './support/configuration.ts';

async function fixture(t: TestContext) {
	const directory = await mkdtemp(path.join(tmpdir(), 'detector-export-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	const root = path.join(directory, 'detections');
	const archive = new DetectionArchive(root);
	return { directory, root, archive };
}

async function event(root: string, category: string, stage: string, timestamp: string) {
	const folder = path.join(root, category, stage, timestamp);
	await mkdir(folder, { recursive: true });
	const metadata = {
		timestamp,
		validated: true,
		confidence: 0.9,
		confidences: { activity: 0.9 },
		detections: 1,
		start: '2026-09-22T12:00:00',
		end: '2026-09-22T12:00:02',
		duration: 2
	};
	await writeFile(path.join(folder, 'metadata.json'), JSON.stringify(metadata));
	await writeFile(path.join(folder, 'video.mp4'), `original video ${timestamp}`);
	return folder;
}

async function unzip(response: Response) {
	assert.equal(response.status, 200);
	assert.equal(response.headers.get('content-type'), 'application/zip');
	assert.equal(response.headers.get('cache-control'), 'no-store');
	assert.match(response.headers.get('content-disposition')!, /^attachment; filename=".*\.zip"$/);
	return unzipSync(new Uint8Array(await response.arrayBuffer()));
}

test('downloads group manually reviewed events by their effective verdict and retain provenance', async (t) => {
	const { root, archive } = await fixture(t);
	const timestamp = '2026-09-22T12-00-00';
	await event(root, 'activity', 'approved', timestamp);
	await archive.review({ type: 'activity', archiveStage: 'approved', timestamp }, false, 'web');
	const files = await unzip(
		await exportRecordings(
			archive,
			{ stage: 'rejected', from: '2026-09-22' },
			new Request('http://localhost/export')
		)
	);
	const base = `detections/activity/rejected/${timestamp}/`;
	// One metadata file carries both the person's review and the validator's own verdict.
	const exported = JSON.parse(Buffer.from(files[base + 'metadata.json']).toString());
	assert.equal(exported.review.validated, false);
	assert.equal(exported.review.source, 'web');
	assert.equal(exported.validated, true);
	assert.ok(files[base + 'video.mp4']);
	assert.equal(
		(await exportRecordings(archive, { stage: 'approved' }, new Request('http://localhost/export')))
			.status,
		404
	);
});

test('reviewed recordings with matching timestamps never overwrite each other in the ZIP', async (t) => {
	const { root, archive } = await fixture(t);
	const timestamp = '2026-09-22T12-00-00';
	await event(root, 'activity', 'approved', timestamp);
	await event(root, 'activity', 'rejected', timestamp);
	await archive.review({ type: 'activity', archiveStage: 'rejected', timestamp }, true, 'web');
	const files = await unzip(
		await exportRecordings(archive, {}, new Request('http://localhost/export'))
	);
	assert.equal(Object.keys(files).filter((name) => name.endsWith('/metadata.json')).length, 2);
	assert.ok(files[`detections/activity/approved/${timestamp}-approved/video.mp4`]);
	assert.ok(files[`detections/activity/approved/${timestamp}-rejected/video.mp4`]);
});

test('export dates are optional, inclusive calendar dates with strict request validation', () => {
	for (const valid of [
		{},
		{ from: '2024-02-29' },
		{ to: '2026-09-22' },
		{ from: '2026-09-22', to: '2026-09-22' }
	])
		assert.equal(v.safeParse(recordingExportInput, valid).success, true);
	for (const invalid of [
		{ from: '2026-02-29' },
		{ to: '2026-04-31' },
		{ from: 'not-a-date' },
		{ from: '2026-09-23', to: '2026-09-22' },
		{ from: '2026-09-22T12:00:00Z' },
		{ type: '..' },
		{ type: '../settings' },
		{ type: 'C:\\settings' },
		{ stage: '.pending' }
	])
		assert.equal(v.safeParse(recordingExportInput, invalid).success, false);
});

test('export selection matches category, stage and whole days without timezone conversion', async (t) => {
	const { root, archive } = await fixture(t);
	for (const timestamp of [
		'2026-09-21T23-59-59.999999',
		'2026-09-22T00-00-00.000000',
		'2026-09-22T23-59-59.999999',
		'2026-09-23T00-00-00.000000'
	])
		await event(root, 'activity', 'approved', timestamp);
	await event(root, 'activity', 'rejected', '2026-09-22T12-00-00');
	await event(root, 'other', 'approved', '2026-09-22T12-00-00');
	await event(root, 'activity', '.pending', '2026-09-22T12-00-00');
	const filter = {
		type: 'activity',
		stage: 'approved' as const,
		from: '2026-09-22',
		to: '2026-09-22'
	};
	const chosen = await archive.locations(filter);
	assert.equal(chosen.length, 2);
	assert.ok(chosen.every((item) => item.timestamp.startsWith('2026-09-22')));
	assert.equal((await archive.locations({ ...filter, to: undefined })).length, 3);
	assert.equal((await archive.locations({ ...filter, from: undefined })).length, 3);
	assert.equal((await archive.locations({})).length, 6);
	const files = await unzip(
		await exportRecordings(archive, filter, new Request('http://localhost/export'))
	);
	assert.equal(Object.keys(files).filter((name) => name.endsWith('metadata.json')).length, 2);
	assert.ok(
		Object.keys(files).every((name) => name === 'README.txt' || name.includes('/2026-09-22T'))
	);
});

test('ZIP includes original media and metadata across all pages, but no configuration or pending files', async (t) => {
	const { directory, root, archive } = await fixture(t);
	for (let minute = 0; minute < 30; minute++)
		await event(
			root,
			'activity',
			'approved',
			`2026-09-22T12-${String(minute).padStart(2, '0')}-00`
		);
	const timestamp = '2026-09-22T12-00-00';
	const folder = path.join(root, 'activity', 'approved', timestamp);
	for (const name of ['clean.jpg', 'best.jpg', `${timestamp}_0.jpg`])
		await writeFile(path.join(folder, name), `original image ${name}`);
	await writeFile(path.join(directory, 'config.json'), 'private-password');
	await writeFile(path.join(folder, 'config.json'), 'private-token');
	await mkdir(path.join(folder, 'nested'));
	await writeFile(path.join(folder, 'nested', 'private.jpg'), 'not an event image');
	const files = await unzip(
		await exportRecordings(archive, {}, new Request('http://localhost/export'))
	);
	assert.equal(Object.keys(files).filter((name) => name.endsWith('/metadata.json')).length, 30);
	for (const name of ['clean.jpg', 'best.jpg', `${timestamp}_0.jpg`, 'video.mp4', 'metadata.json'])
		assert.deepEqual(
			Buffer.from(files[`detections/activity/approved/${timestamp}/${name}`]),
			await readFile(path.join(folder, name))
		);
	assert.ok(!Object.keys(files).some((name) => name.includes('config') || name.includes('nested')));
	assert.doesNotMatch(
		Buffer.concat(Object.values(files)).toString(),
		/private-password|private-token/
	);
	assert.match(
		Buffer.from(files['README.txt']).toString(),
		/not a verified bounding-box annotation/
	);
});

test('an export of photos only holds the picture without boxes and the details of each event', async (t) => {
	const { root, archive } = await fixture(t);
	const timestamp = '2026-09-22T12-00-00';
	await event(root, 'activity', 'approved', timestamp);
	const folder = path.join(root, 'activity', 'approved', timestamp);
	for (const name of ['clean.jpg', 'best.jpg', `${timestamp}_0.jpg`])
		await writeFile(path.join(folder, name), `image ${name}`);
	const files = await unzip(
		await exportRecordings(archive, { content: 'photos' }, new Request('http://localhost/export'))
	);
	assert.deepEqual(Object.keys(files).sort(), [
		'PHOTOS-ONLY.txt',
		'README.txt',
		`detections/activity/approved/${timestamp}/clean.jpg`,
		`detections/activity/approved/${timestamp}/metadata.json`
	]);
	assert.match(Buffer.from(files['PHOTOS-ONLY.txt']).toString(), /original photos only/);
});

test(
	'export ignores linked media and rejects a category link outside the archive',
	{ skip: process.platform === 'win32' },
	async (t) => {
		const { directory, root, archive } = await fixture(t);
		const folder = await event(root, 'activity', 'approved', '2026-09-22T12-00-00');
		const secret = path.join(directory, 'private.jpg');
		await writeFile(secret, 'private image');
		await symlink(secret, path.join(folder, 'linked.jpg'));
		const files = await unzip(
			await exportRecordings(archive, {}, new Request('http://localhost/export'))
		);
		assert.ok(!Object.keys(files).some((name) => name.endsWith('linked.jpg')));
		const outside = path.join(directory, 'outside');
		await event(outside, 'private', 'approved', '2026-09-22T12-00-00');
		await symlink(path.join(outside, 'private'), path.join(root, 'external'));
		// The link is refused while listing recordings, before any download starts.
		await assert.rejects(
			exportRecordings(archive, { type: 'external' }, new Request('http://localhost/export')),
			/Invalid archive path/
		);
	}
);

test('missing archives and empty date ranges do not produce misleading empty ZIPs', async (t) => {
	const { root, archive } = await fixture(t);
	assert.equal(
		(await exportRecordings(archive, {}, new Request('http://localhost/export'))).status,
		404
	);
	await event(root, 'activity', 'approved', '2026-09-22T12-00-00');
	const response = await exportRecordings(
		archive,
		{ to: '2025-01-01' },
		new Request('http://localhost/export')
	);
	assert.equal(response.status, 404);
	assert.match(await response.text(), /No recordings match/);
});

for (const cancellation of ['request', 'body'] as const) {
	test(
		`${cancellation} cancellation closes the current file without reading the whole recording`,
		{ timeout: 5000 },
		async (t) => {
			const { directory } = await fixture(t);
			const file = path.join(directory, 'large.mp4');
			await writeFile(file, '');
			await truncate(file, 64 * 1024 * 1024);
			const streams: ReadStream[] = [];
			const emit = ReadStream.prototype.emit;
			t.mock.method(
				ReadStream.prototype,
				'emit',
				function (this: ReadStream, event: string | symbol, ...args: unknown[]) {
					if (event === 'open') streams.push(this);
					return emit.call(this, event, ...args);
				}
			);
			const controller = new AbortController();
			t.after(() => controller.abort());
			const request = new Request('http://localhost/export', { signal: controller.signal });
			const response = zipDownload('recordings.zip', [{ name: 'large.mp4', file }], request);
			const reader = response.body!.getReader();
			await reader.read();
			while (!streams.length) await delay(5);
			await delay(30);
			assert.ok(
				streams[0].bytesRead < 2 * 1024 * 1024,
				'a slow download must backpressure disk reads'
			);
			if (cancellation === 'body') await reader.cancel();
			else {
				controller.abort();
				await assert.rejects(reader.closed, { name: 'AbortError' });
			}
			while (!streams[0].closed) await delay(5);
			assert.ok(streams[0].destroyed);
		}
	);
}

test('file errors reject the download instead of completing an incomplete ZIP', async (t) => {
	const { directory } = await fixture(t);
	const response = zipDownload(
		'recordings.zip',
		[{ name: 'missing.mp4', file: path.join(directory, 'missing.mp4') }],
		new Request('http://localhost/export')
	);
	await assert.rejects(response.arrayBuffer(), { code: 'ENOENT' });
});

test('settings backup preserves cameras, detector options and alerts, and imports into a new setup', async (t) => {
	const { directory, files, store } = await settingsStore(t);
	const source = 'rtsp://farmer:private-password@camera.example.test/live';
	await writeFile(
		files.config,
		JSON.stringify({
			detectors: [
				{
					detection: { source: [source], interval: 3 },
					yolo: { model: 'yolo11n.pt' },
					exporters: {
						disk: [{ directory: 'activity' }],
						telegram: [{ token: 'private-token', chat: '1234' }]
					}
				}
			]
		})
	);
	await writeFile(
		files.app,
		JSON.stringify({
			streams: [{ id: 'barn', source, label: 'Barn' }],
			detectors: [{ label: 'Activity', preset: 'general' }],
			telegrams: [{ label: 'Phone', token: 'private-token', chat: '1234' }]
		})
	);
	const before = await readFile(files.config);
	const expected = await store.read();
	await store.updateDevices(() => [
		{ id: 'local-device', name: 'Phone', hash: 'device-hash', created: 1, expires: 9999999999999 }
	]);
	const zipped = await unzip(await backupSettings(store, new Request('http://localhost/backup')));
	assert.deepEqual(Object.keys(zipped).sort(), ['README.txt', 'app.json', 'config.json']);
	assert.deepEqual(JSON.parse(Buffer.from(zipped['config.json']).toString()), expected.config);
	assert.deepEqual(JSON.parse(Buffer.from(zipped['app.json']).toString()), expected.app);
	assert.equal((await store.readDevices()).length, 1);
	assert.match(Buffer.from(zipped['README.txt']).toString(), /Keep this ZIP private/);
	assert.deepEqual(await readFile(files.config), before);
	const extracted = path.join(directory, 'extracted');
	const destination = path.join(directory, 'restored');
	await mkdir(extracted);
	await mkdir(destination);
	for (const [name, data] of Object.entries(zipped))
		await writeFile(path.join(extracted, name), data);
	const restored = new ConfigurationStore({
		config: path.join(destination, 'config.json'),
		app: path.join(destination, 'app.json')
	});
	const importer = new InstallationImport(destination, restored);
	const summary = await importer.inspect(extracted);
	await importer.start(summary.id, false);
	await importer.settled();
	assert.equal((await importer.getStatus()).phase, 'complete');
	assert.deepEqual(await restored.read(), expected);
});

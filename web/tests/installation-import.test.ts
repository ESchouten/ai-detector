import assert from 'node:assert/strict';
import { test, type TestContext } from 'node:test';
import { mkdtemp, mkdir, readFile, rm, stat, symlink, utimes, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { InstallationImport } from '../src/lib/server/installation-import/service.ts';
import { ConfigurationStore } from '../src/lib/server/configuration/store.ts';
import { DetectionArchive, archivePath } from '../src/lib/server/archive.ts';
import { availableSpace, exists } from '../src/lib/server/installation-import/files.ts';
import { readJson, writeJson } from '../src/lib/server/json-file.ts';
import type { Configuration } from '../src/lib/schema.ts';

const camera = 'rtsp://farmer:private-password@camera.example.test/live';
const event = path.join('detections', 'mounting', 'approved', '2025-01-02T12-00-00');
const metadata = {
	timestamp: '2025-01-02T12-00-00',
	validated: true,
	confidence: 0.9,
	confidences: { mounting: 0.9 },
	detections: 2,
	start: '2025-01-02T12:00:00',
	end: '2025-01-02T12:00:02',
	duration: 2
};

async function fixture(t: TestContext) {
	const directory = await mkdtemp(path.join(tmpdir(), 'installation-import-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	const source = path.join(directory, 'previous');
	const destination = path.join(directory, 'new');
	await mkdir(path.join(source, event), { recursive: true });
	await mkdir(destination);
	const config = {
		detectors: [
			{
				detection: { source: camera, interval: 3 },
				yolo: {
					model: 'custom.pt',
					strategy: 'LATEST',
					frames_min: 6,
					confidence: { mounting: 0.8 }
				},
				exporters: {
					disk: { directory: 'mounting' },
					telegram: { token: 'private-token', chat: '1234', include_video: false, alert_every: 3 },
					webhook: { url: 'https://example.test/alerts' }
				}
			}
		]
	};
	const app = {
		streams: [{ label: 'Barn', source: camera }],
		detectors: [{ label: 'Cow catcher', preset: 'cow-catcher' }],
		telegrams: [{ label: 'My phone', token: 'private-token', chat: '1234' }]
	};
	await writeJson(path.join(source, 'config.json'), config);
	await writeJson(path.join(source, 'app.json'), app);
	await writeFile(path.join(source, 'custom.pt'), 'original model');
	await writeJson(path.join(source, event, 'metadata.json'), metadata);
	await writeFile(path.join(source, event, 'best.jpg'), 'original picture');
	await writeFile(path.join(source, event, 'video.mp4'), 'original recording');
	const calls: string[] = [];
	const store = new ConfigurationStore(
		{ config: path.join(destination, 'config.json'), app: path.join(destination, 'app.json') },
		async () => [],
		() => ({
			validate: async () => {
				calls.push('validate');
			},
			apply: async () => {
				calls.push('apply');
			},
			stop: async () => {
				calls.push('stop');
			},
			fail: () => {
				calls.push('fail');
			}
		})
	);
	const importer = new InstallationImport(destination, store);
	return { source, destination, config, app, calls, store, importer };
}

async function finish(importer: InstallationImport, id: string, keepRecordings = false) {
	await importer.start(id, keepRecordings);
	await importer.settled();
	const status = await importer.getStatus();
	assert.equal(status.phase, 'complete', status.message);
	return status;
}

test('import does not overwrite an AI connection saved before adding cameras', async (t) => {
	const { source, store, importer } = await fixture(t);
	await store.saveLlm({ label: 'My AI', model: 'openai/vision', key: 'test-only' });
	await assert.rejects(importer.inspect(source), /already has a setup/);
	await assert.rejects(
		store.initialize(
			{ config: { detectors: [] }, app: { streams: [], detectors: [], telegrams: [], llms: [] } },
			async () => assert.fail('Existing settings must not be replaced')
		),
		/already has a setup/
	);
	assert.equal((await store.read()).app.llms[0].label, 'My AI');
});

test('imports legacy settings and original recordings into setup without starting monitoring', async (t) => {
	const { source, destination, config, app, importer, store, calls } = await fixture(t);
	const original = await readFile(path.join(source, 'config.json'));
	const summary = await importer.inspect(source);
	assert.deepEqual([summary.cameras, summary.detectors, summary.recordings], [1, 1, 1]);
	assert.match(summary.notes[0], /strategy/);
	assert.doesNotMatch(JSON.stringify(await importer.getStatus()), /private-password|private-token/);
	assert.equal(await exists(path.join(destination, 'config.json')), false);
	assert.deepEqual(calls, []);
	await finish(importer, summary.id);
	const saved = await store.read();
	assert.equal(saved.app.streams[0].label, 'Barn');
	assert.ok(saved.app.streams[0].id);
	assert.deepEqual(saved.app.detectors, app.detectors);
	assert.deepEqual(saved.app.telegrams, app.telegrams);
	assert.deepEqual(saved.config.detectors[0].detection, {
		...config.detectors[0].detection,
		source: [camera]
	});
	assert.deepEqual(saved.config.detectors[0].exporters?.telegram, [
		config.detectors[0].exporters.telegram
	]);
	assert.equal(saved.config.detectors[0].yolo?.frames_min, 6);
	assert.ok(!('strategy' in saved.config.detectors[0].yolo!));
	const model = saved.config.detectors[0].yolo!.model;
	assert.match(model, /^imported-files/);
	assert.equal(await readFile(path.join(destination, model), 'utf8'), 'original model');
	assert.deepEqual(calls, ['validate']);
	const archive = new DetectionArchive(path.join(destination, 'detections'));
	const page = await archive.page({ offset: 0, limit: 10 });
	assert.equal(page.items[0].timestamp, metadata.timestamp);
	assert.equal(page.items[0].type, 'mounting');
	assert.equal(
		await readFile(path.join(destination, event, 'video.mp4'), 'utf8'),
		'original recording'
	);
	assert.deepEqual(await readFile(path.join(source, 'config.json')), original);
	assert.equal(await readFile(path.join(source, event, 'video.mp4'), 'utf8'), 'original recording');
	assert.equal(await exists(path.join(destination, '.installation-import')), false);
	assert.equal(await exists(path.join(destination, 'runtime.json')), false);
});

test('relocates shared local camera files and ONNX tensors and preserves standalone camera names', async (t) => {
	const { source, destination, importer, store } = await fixture(t);
	await mkdir(path.join(source, 'models'));
	await writeFile(path.join(source, 'models', 'custom.onnx'), 'onnx');
	await writeFile(path.join(source, 'models', 'custom.onnx.data'), 'tensors');
	await writeFile(path.join(source, 'barn.mp4'), 'camera clip');
	await writeJson(path.join(source, 'config.json'), {
		detectors: [
			{ detection: { source: ['barn.mp4', camera] }, yolo: { model: 'models/custom.onnx' } },
			{ detection: { source: 'barn.mp4' }, yolo: { model: 'models/custom.onnx' } }
		]
	});
	await writeJson(path.join(source, 'app.json'), {
		streams: [
			{ source: 'barn.mp4', label: 'Recorded barn' },
			{ source: '0', label: 'USB camera' }
		]
	});
	const summary = await importer.inspect(source);
	assert.equal(summary.cameras, 3);
	await finish(importer, summary.id);
	const saved = await store.read();
	const [first, second] = saved.config.detectors;
	assert.equal(first.yolo!.model, second.yolo!.model);
	assert.equal(first.detection.source[0], second.detection.source[0]);
	assert.equal(saved.app.streams[0].source, first.detection.source[0]);
	assert.equal(saved.app.streams[0].label, 'Recorded barn');
	assert.equal(saved.app.streams[1].source, '0');
	assert.equal(
		await readFile(path.join(destination, first.yolo!.model + '.data'), 'utf8'),
		'tensors'
	);
	assert.equal(
		await readFile(path.join(destination, first.detection.source[0]), 'utf8'),
		'camera clip'
	);
});

test('unknown configuration settings and missing explicit model paths block import without modifying data', async (t) => {
	const { source, destination, config, importer } = await fixture(t);
	await writeJson(path.join(source, 'config.json'), { ...config, unknown_setting: true });
	await assert.rejects(importer.inspect(source), /unsupported property "unknown_setting"/);
	config.detectors[0].yolo.model = 'models/missing.pt';
	await writeJson(path.join(source, 'config.json'), config);
	await assert.rejects(importer.inspect(source), /model.*missing/);
	assert.equal(await exists(path.join(destination, 'config.json')), false);
	assert.equal(await exists(path.join(destination, 'detections')), false);
});

test('bare models without local weights stay under Ultralytics download management with a notice', async (t) => {
	const { source, config, importer, store } = await fixture(t);
	config.detectors[0].yolo.model = 'yolo11n.pt';
	await writeJson(path.join(source, 'config.json'), config);
	await rm(path.join(source, 'app.json'));
	const summary = await importer.inspect(source);
	assert.ok(summary.notes.some((note) => note.includes('Ultralytics')));
	await finish(importer, summary.id);
	assert.equal((await store.read()).config.detectors[0].yolo!.model, 'yolo11n.pt');
});

test('keeping recordings uses the existing archive and its normal media boundaries', async (t) => {
	const { source, destination, importer } = await fixture(t);
	const summary = await importer.inspect(source);
	const status = await finish(importer, summary.id, true);
	assert.equal(status.totalBytes, summary.bytes - summary.recordingBytes);
	const root = path.join(destination, 'detections');
	assert.equal((await new DetectionArchive(root).page({ offset: 0, limit: 10 })).items.length, 1);
	const video = await archivePath(root, 'mounting', 'approved', metadata.timestamp, 'video.mp4');
	assert.equal(await readFile(video, 'utf8'), 'original recording');
	await writeFile(path.join(destination, event, 'clean.jpg'), 'new picture');
	assert.equal(await readFile(path.join(source, event, 'clean.jpg'), 'utf8'), 'new picture');
});

test('source changes are caught before publishing and the user can select the folder again', async (t) => {
	const { source, destination, config, importer } = await fixture(t);
	const summary = await importer.inspect(source);
	config.detectors[0].detection.interval = 10;
	await writeJson(path.join(source, 'config.json'), config);
	await importer.start(summary.id, false);
	await importer.settled();
	const status = await importer.getStatus();
	assert.equal(status.phase, 'failed');
	assert.match(status.message!, /old installation changed/);
	assert.equal(status.canRestart, true);
	assert.equal(await exists(path.join(destination, 'config.json')), false);
	const next = await importer.inspect(source);
	await finish(importer, next.id);
});

test('an interrupted copy resumes across application restarts without copying completed files again', async (t) => {
	const { source, destination, importer, store } = await fixture(t);
	const summary = await importer.inspect(source);
	const model = path.join(source, 'custom.pt');
	const original = await stat(model);
	await rm(model);
	await importer.start(summary.id, false);
	await importer.settled();
	assert.equal((await importer.getStatus()).phase, 'failed');
	const stagedVideo = path.join(destination, '.installation-import', 'files', event, 'video.mp4');
	const before = await stat(stagedVideo);
	await writeFile(model, 'original model');
	await utimes(model, original.atime, original.mtime);
	// Store the filesystem's timestamp precision, as it can differ after utimes on Windows.
	const manifest = path.join(destination, '.installation-import', 'job.json');
	const job = JSON.parse(await readFile(manifest, 'utf8'));
	job.files.find(
		(file: { source: string }) => path.basename(file.source) === 'custom.pt'
	).modified = (await stat(model)).mtimeMs;
	await writeJson(manifest, job);
	const resumed = new InstallationImport(destination, store);
	assert.equal((await resumed.getStatus()).phase, 'ready');
	await finish(resumed, summary.id);
	assert.equal((await stat(path.join(destination, event, 'video.mp4'))).ino, before.ino);
});

test('publication interrupted before settings commit resumes without losing the imported archive', async (t) => {
	const { source, destination, importer, store } = await fixture(t);
	const summary = await importer.inspect(source);
	const interruption = t.mock.method(
		store,
		'initialize',
		async (_document: Configuration, publish: () => Promise<void>) => {
			await publish();
			throw new Error('simulated interruption');
		}
	);
	await importer.start(summary.id, false);
	await importer.settled();
	assert.equal((await importer.getStatus()).phase, 'failed');
	assert.equal((await importer.getStatus()).canRestart, false);
	assert.equal(await exists(path.join(destination, event, 'video.mp4')), true);
	assert.equal(await exists(path.join(destination, 'config.json')), false);
	interruption.mock.restore();
	await finish(new InstallationImport(destination, store), summary.id);
	assert.equal((await store.read()).app.streams[0].label, 'Barn');
});

test('a crash between saving app.json and config.json can finish the same import', async (t) => {
	const { source, destination, importer, store, calls } = await fixture(t);
	const summary = await importer.inspect(source);
	const interruption = t.mock.method(
		store,
		'initialize',
		async (document: Configuration, publish: () => Promise<void>) => {
			await publish();
			const { identifyCameras } = await import('../src/lib/server/configuration/cameras.ts');
			await writeJson(path.join(destination, 'app.json'), identifyCameras(document).app);
			throw new Error('simulated interruption');
		}
	);
	await importer.start(summary.id, false);
	await importer.settled();
	interruption.mock.restore();
	await finish(new InstallationImport(destination, store), summary.id);
	assert.equal((await store.read()).config.detectors.length, 1);
	assert.deepEqual(calls, ['validate']);
});

test('an already committed import is recognized after a restart and does not restart the detector', async (t) => {
	const { source, destination, importer, store, calls } = await fixture(t);
	const summary = await importer.inspect(source);
	const initialize = store.initialize.bind(store);
	const interruption = t.mock.method(
		store,
		'initialize',
		async (...args: Parameters<typeof store.initialize>) => {
			await initialize(...args);
			throw new Error('simulated interruption after commit');
		}
	);
	await importer.start(summary.id, false);
	await importer.settled();
	interruption.mock.restore();
	await finish(new InstallationImport(destination, store), summary.id);
	assert.deepEqual(calls, ['validate']);
});

test('existing destination recordings and setups are never replaced, including changes during import', async (t) => {
	const { source, destination, importer, store } = await fixture(t);
	await mkdir(path.join(destination, 'detections'));
	await assert.rejects(importer.inspect(source), /will not overwrite/);
	await rm(path.join(destination, 'detections'), { recursive: true });
	const summary = await importer.inspect(source);
	await store.saveStream({ label: 'New camera', source: '0' });
	await importer.start(summary.id, false);
	await importer.settled();
	assert.match((await importer.getStatus()).message!, /already has a setup/);
	assert.equal((await store.read()).app.streams[0].label, 'New camera');
	assert.equal(await exists(path.join(destination, 'detections')), false);
	await assert.rejects(importer.inspect(source), /already has a setup/);
});

test('paths cannot import into themselves or traverse linked recording folders', async (t) => {
	const { source, destination, importer } = await fixture(t);
	await assert.rejects(importer.inspect(destination), /outside/);
	await assert.rejects(importer.inspect(path.dirname(destination)), /outside/);
	await assert.rejects(importer.inspect(path.join(source, 'config.json')), /folder containing/);
	await symlink(
		destination,
		path.join(source, 'detections', 'linked'),
		process.platform === 'win32' ? 'junction' : 'dir'
	);
	await assert.rejects(importer.inspect(source), /symbolic link/);
});

test('insufficient space is reported before copying', async (t) => {
	const { destination } = await fixture(t);
	await assert.rejects(
		availableSpace(destination, Number.MAX_SAFE_INTEGER),
		/not enough free space/
	);
	assert.equal(await readJson(path.join(destination, 'config.json')), null);
});

test('cancelling removes private staging, preserves the source, and leaves setup available', async (t) => {
	const { source, destination, importer, store } = await fixture(t);
	const summary = await importer.inspect(source);
	await rm(path.join(source, 'custom.pt'));
	await importer.start(summary.id, false);
	await importer.settled();
	assert.equal((await importer.getStatus()).phase, 'failed');
	await importer.cancel();
	assert.equal((await importer.getStatus()).phase, 'idle');
	assert.equal(await exists(path.join(destination, '.installation-import')), false);
	assert.equal(await readFile(path.join(source, event, 'video.mp4'), 'utf8'), 'original recording');
	assert.equal((await store.read()).config.detectors.length, 0);
});

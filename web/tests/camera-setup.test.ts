import assert from 'node:assert/strict';
import fs, { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { syncBuiltinESMExports } from 'node:module';
import path from 'node:path';
import { test, type TestContext } from 'node:test';
import * as v from 'valibot';
import { cameraInput, streamInput } from '../src/lib/configuration.ts';
import { ConfigurationStore } from '../src/lib/server/configuration/store.ts';
import {
	cameraArchiveSelection,
	cameraSetupStatus
} from '../src/lib/server/configuration/camera-setup.ts';

const source = 'rtsp://farmer:secret@camera.test/yard';
const verifiedAt = '2026-09-22T10:00:00.000Z';
const connection = { address: 'http://camera.test/onvif/device_service', profileToken: 'yard' };

async function fixture(t: TestContext) {
	const directory = await mkdtemp(path.join(tmpdir(), 'camera-progress-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	const files = {
		config: path.join(directory, 'config.json'),
		app: path.join(directory, 'app.json')
	};
	return { files, store: new ConfigurationStore(files) };
}

async function readyCamera(store: ConfigurationStore) {
	const camera = await store.saveCamera(
		{ label: 'Yard', source, preset: 'general', connection },
		verifiedAt
	);
	const { signature } = cameraArchiveSelection(await store.read(), camera.id);
	await store.recordArchiveCheck(camera.id, signature, verifiedAt);
	await store.skipCameraAlerts(camera.id);
	return camera;
}

test('camera progress and non-secret ONVIF details survive reopening and renaming', async (t) => {
	const { files, store } = await fixture(t);
	const camera = await readyCamera(store);
	await store.finishCameraSetup(camera.id, async () => true);
	await store.saveCamera({ id: camera.id, label: 'Main yard', source, preset: 'keep' });
	const reopened = await new ConfigurationStore(files).read();
	assert.equal(reopened.app.streams[0].id, camera.id);
	assert.deepEqual(reopened.app.streams[0].connection, connection);
	const progress = cameraSetupStatus(reopened, camera.id);
	assert.equal(progress.pictureVerifiedAt, verifiedAt);
	assert.equal(progress.archiveVerifiedAt, verifiedAt);
	assert.equal(progress.alertsSkipped, true);
	assert.ok(progress.completedAt);
	assert.equal(JSON.stringify(reopened.app.streams[0].connection).includes('secret'), false);
});

test('setup completion requires an explicit alert choice and real current monitoring', async (t) => {
	const { files, store } = await fixture(t);
	const camera = await store.saveCamera({ label: 'Yard', source, preset: 'general' }, verifiedAt);
	const { signature } = cameraArchiveSelection(await store.read(), camera.id);
	await store.recordArchiveCheck(camera.id, signature, verifiedAt);
	await assert.rejects(
		store.finishCameraSetup(camera.id, async () => true),
		/choose whether to connect alerts/
	);
	await store.skipCameraAlerts(camera.id);
	await assert.rejects(
		store.finishCameraSetup(camera.id, async () => false),
		/Monitoring has not been verified/
	);
	assert.equal(cameraSetupStatus(await store.read(), camera.id).completedAt, undefined);
	await store.finishCameraSetup(camera.id, async () => true);
	assert.ok(cameraSetupStatus(await new ConfigurationStore(files).read(), camera.id).completedAt);
});

test('view-only setup can finish after picture confirmation without monitoring, alerts or an archive test', async (t) => {
	const { store } = await fixture(t);
	const camera = await store.saveCamera({ label: 'Yard', source, preset: 'view-only' });
	await assert.rejects(
		store.finishCameraSetup(camera.id, async () => false),
		/Confirm the picture/
	);
	await store.saveCamera({ id: camera.id, label: 'Yard', source, preset: 'keep' }, verifiedAt);
	await store.finishCameraSetup(camera.id, async () => false);
	const progress = cameraSetupStatus(await store.read(), camera.id);
	assert.equal(progress.monitored, false);
	assert.equal(progress.archiveDestinations, 0);
	assert.equal(progress.alertsSkipped, false);
	assert.ok(progress.completedAt);
});

test('password or source changes preserve camera identity but invalidate earlier proofs', async (t) => {
	const { store } = await fixture(t);
	const camera = await readyCamera(store);
	await store.finishCameraSetup(camera.id, async () => true);
	const updatedSource = 'rtsp://farmer:new-password@camera.test/yard';
	const nextCheck = '2026-09-22T11:00:00.000Z';
	await store.saveCamera(
		{ id: camera.id, label: 'Yard', source: updatedSource, preset: 'keep', connection },
		nextCheck
	);
	const updated = await store.read();
	assert.equal(updated.app.streams[0].id, camera.id);
	assert.deepEqual(updated.app.streams[0].connection, connection);
	const progress = cameraSetupStatus(updated, camera.id);
	assert.equal(progress.pictureVerifiedAt, nextCheck);
	assert.equal(progress.archiveVerifiedAt, undefined);
	assert.equal(progress.completedAt, undefined);
	assert.equal(progress.alertsSkipped, true);
	await store.saveStream({ original: updatedSource, label: 'Yard', source });
	const legacyEdit = await store.read();
	assert.equal(legacyEdit.app.streams[0].connection, undefined);
	assert.equal(cameraSetupStatus(legacyEdit, camera.id).pictureVerifiedAt, undefined);
});

test('changing archive destinations invalidates its proof and rejects an obsolete in-flight check', async (t) => {
	const { files, store } = await fixture(t);
	const camera = await readyCamera(store);
	await store.finishCameraSetup(camera.id, async () => true);
	const document = await store.read();
	const { signature } = cameraArchiveSelection(document, camera.id);
	document.config.detectors[0].exporters!.disk = [{ directory: 'other-location' }];
	await store.replace(document);
	const before = await readFile(files.app, 'utf8');
	const progress = cameraSetupStatus(await store.read(), camera.id);
	assert.equal(progress.pictureVerifiedAt, verifiedAt);
	assert.equal(progress.archiveVerifiedAt, undefined);
	assert.equal(progress.completedAt, undefined);
	await assert.rejects(
		store.recordArchiveCheck(camera.id, signature, verifiedAt),
		/settings changed during/
	);
	assert.equal(await readFile(files.app, 'utf8'), before);
});

test('advanced model changes require completion again while preserving relevant historical picture and archive checks', async (t) => {
	const { store } = await fixture(t);
	const camera = await readyCamera(store);
	await store.finishCameraSetup(camera.id, async () => true);
	const document = await store.read();
	await store.saveDetector({
		original: document.app.detectors[0].label,
		meta: document.app.detectors[0],
		detector: { ...document.config.detectors[0], yolo: { model: 'different.pt' } }
	});
	const progress = cameraSetupStatus(await store.read(), camera.id);
	assert.equal(progress.completedAt, undefined);
	assert.equal(progress.pictureVerifiedAt, verifiedAt);
	assert.equal(progress.archiveVerifiedAt, verifiedAt);
});

test('Finish checks runtime after a queued rule change has restarted monitoring', async (t) => {
	const { files, store } = await fixture(t);
	const camera = await readyCamera(store);
	let monitoring = true;
	let callbackCalled = false;
	const queued = new ConfigurationStore(files, () => ({
		validate: async () => {},
		apply: async () => {
			monitoring = false;
		},
		stop: async () => {},
		fail: () => {}
	}));
	const document = await queued.read();
	const update = queued.saveDetector({
		original: document.app.detectors[0].label,
		meta: document.app.detectors[0],
		detector: { ...document.config.detectors[0], yolo: { model: 'new.pt' } }
	});
	const finish = queued.finishCameraSetup(camera.id, async () => {
		callbackCalled = true;
		return monitoring;
	});
	assert.equal(callbackCalled, false);
	await update;
	await assert.rejects(finish, /Monitoring has not been verified/);
	assert.equal(callbackCalled, true);
	assert.equal(cameraSetupStatus(await queued.read(), camera.id).completedAt, undefined);
});

test('failed progress persistence does not claim completion and retry succeeds', async (t) => {
	const { files, store } = await fixture(t);
	const camera = await readyCamera(store);
	const before = await readFile(files.app, 'utf8');
	const write = fs.writeFile;
	const failure = Object.assign(new Error('Settings are not writable'), { code: 'EACCES' });
	const blocked = t.mock.method(
		fs,
		'writeFile',
		async (...args: Parameters<typeof fs.writeFile>) => {
			if (String(args[0]).startsWith(files.app)) throw failure;
			return write(...args);
		}
	);
	syncBuiltinESMExports();
	t.after(() => {
		blocked.mock.restore();
		syncBuiltinESMExports();
	});
	await assert.rejects(
		store.finishCameraSetup(camera.id, async () => true),
		(error) => error === failure
	);
	assert.equal(await readFile(files.app, 'utf8'), before);
	assert.equal(cameraSetupStatus(await store.read(), camera.id).completedAt, undefined);
	blocked.mock.restore();
	syncBuiltinESMExports();
	await store.finishCameraSetup(camera.id, async () => true);
	assert.ok(cameraSetupStatus(await store.read(), camera.id).completedAt);
});

test('client camera input cannot forge progress and rejects secrets in reusable connection metadata', () => {
	const input = { label: 'Yard', source, preset: 'general', connection };
	assert.equal(v.safeParse(cameraInput, input).success, true);
	for (const address of [
		'http://farmer:secret@camera.test/onvif',
		'http://camera.test?token=secret',
		'http://camera.test/#secret',
		'rtsp://camera.test/live'
	])
		assert.equal(v.safeParse(cameraInput, { ...input, connection: { address } }).success, false);
	const parsed = v.parse(cameraInput, {
		...input,
		setup: { pictureVerifiedAt: verifiedAt, completedAt: verifiedAt }
	});
	assert.equal('setup' in parsed, false);
	const stream = v.parse(streamInput, {
		label: 'Yard',
		source,
		setup: { completedAt: verifiedAt },
		connection
	});
	assert.equal('setup' in stream, false);
	assert.equal('connection' in stream, false);
});

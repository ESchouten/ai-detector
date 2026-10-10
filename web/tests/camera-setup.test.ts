import { addMonitoredCamera } from './support/configuration.ts';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { promisify } from 'node:util';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test, type TestContext } from 'node:test';
import * as v from 'valibot';
import { cameraInput } from '../src/lib/configuration.ts';
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
	const camera = await addMonitoredCamera(
		store,
		{ label: 'Yard', source, connection },
		'general',
		verifiedAt
	);
	const { signature } = cameraArchiveSelection(await store.read(), camera.id);
	await store.recordArchiveCheck(camera.id, signature, verifiedAt);
	return camera;
}

test('camera progress and non-secret ONVIF details survive reopening and renaming', async (t) => {
	const { files, store } = await fixture(t);
	const camera = await readyCamera(store);
	await store.finishSetup(async () => new Set([camera.id]));
	await store.saveCamera({ id: camera.id, label: 'Main yard', source });
	const reopened = await new ConfigurationStore(files).read();
	assert.equal(reopened.app.streams[0].id, camera.id);
	assert.deepEqual(reopened.app.streams[0].connection, connection);
	const progress = cameraSetupStatus(reopened, camera.id);
	assert.equal(progress.pictureVerifiedAt, verifiedAt);
	assert.equal(progress.archiveVerifiedAt, verifiedAt);
	assert.ok(progress.completedAt);
	assert.equal(JSON.stringify(reopened.app.streams[0].connection).includes('secret'), false);
});

test('setup can finish without phone alerts but still requires real current monitoring', async (t) => {
	const { files, store } = await fixture(t);
	const camera = await addMonitoredCamera(store, { label: 'Yard', source }, 'general', verifiedAt);
	const { signature } = cameraArchiveSelection(await store.read(), camera.id);
	await store.recordArchiveCheck(camera.id, signature, verifiedAt);
	await assert.rejects(
		store.finishSetup(async () => new Set()),
		/Monitoring has not been verified/
	);
	assert.equal(cameraSetupStatus(await store.read(), camera.id).completedAt, undefined);
	await store.finishSetup(async () => new Set([camera.id]));
	assert.ok(cameraSetupStatus(await new ConfigurationStore(files).read(), camera.id).completedAt);
});

test('view-only setup can finish after picture confirmation without monitoring, alerts or an archive test', async (t) => {
	const { store } = await fixture(t);
	const camera = await store.saveCamera({ label: 'Yard', source });
	await assert.rejects(
		store.finishSetup(async () => new Set()),
		/Confirm the picture/
	);
	await store.saveCamera({ id: camera.id, label: 'Yard', source }, verifiedAt);
	await store.finishSetup(async () => new Set());
	const progress = cameraSetupStatus(await store.read(), camera.id);
	assert.equal(progress.monitored, false);
	assert.equal(progress.archiveDestinations, 0);
	assert.ok(progress.completedAt);
});

test('finishing all cameras is atomic and still requires every camera check and current monitoring', async (t) => {
	const { files, store } = await fixture(t);
	const first = await readyCamera(store);
	const second = await store.saveCamera({
		label: 'Entrance',
		source: 'rtsp://camera.test/entrance'
	});
	const before = await readFile(files.app, 'utf8');
	await assert.rejects(
		store.finishSetup(async () => new Set([first.id])),
		/Confirm the picture/
	);
	assert.equal(await readFile(files.app, 'utf8'), before);
	assert.equal(cameraSetupStatus(await store.read(), first.id).completedAt, undefined);
	await store.saveCamera(
		{ id: second.id, label: 'Entrance', source: 'rtsp://camera.test/entrance' },
		verifiedAt
	);
	await assert.rejects(
		store.finishSetup(async () => new Set()),
		/Monitoring has not been verified/
	);
	await store.finishSetup(async () => new Set([first.id]));
	const saved = await new ConfigurationStore(files).read();
	assert.ok(cameraSetupStatus(saved, first.id).completedAt);
	assert.ok(cameraSetupStatus(saved, second.id).completedAt);
});

test('setup lists only the recipients actually assigned to each camera', async (t) => {
	const { store } = await fixture(t);
	const first = await addMonitoredCamera(store, { label: 'Yard', source }, 'general', verifiedAt);
	const second = await addMonitoredCamera(
		store,
		{ label: 'Entrance', source: 'rtsp://camera.test/entrance' },
		'general',
		verifiedAt
	);
	await store.saveAlerts({
		label: 'My phone',
		token: 'token',
		chat: 'chat',
		detectorLabels: ['Yard'],
		received: true
	});
	const saved = await store.read();
	assert.deepEqual(cameraSetupStatus(saved, first.id).alerts, ['My phone']);
	assert.deepEqual(cameraSetupStatus(saved, second.id).alerts, []);
});

test('password or source changes preserve camera identity but invalidate earlier proofs', async (t) => {
	const { store } = await fixture(t);
	const camera = await readyCamera(store);
	await store.finishSetup(async () => new Set([camera.id]));
	const updatedSource = 'rtsp://farmer:new-password@camera.test/yard';
	const nextCheck = '2026-09-22T11:00:00.000Z';
	await store.saveCamera(
		{ id: camera.id, label: 'Yard', source: updatedSource, connection },
		nextCheck
	);
	const updated = await store.read();
	assert.equal(updated.app.streams[0].id, camera.id);
	assert.deepEqual(updated.app.streams[0].connection, connection);
	const progress = cameraSetupStatus(updated, camera.id);
	assert.equal(progress.pictureVerifiedAt, nextCheck);
	assert.equal(progress.archiveVerifiedAt, undefined);
	assert.equal(progress.completedAt, undefined);
	// An address saved without a new picture check keeps neither the earlier check nor its connection.
	await store.saveCamera({ id: camera.id, label: 'Yard', source });
	const unchecked = await store.read();
	assert.equal(unchecked.app.streams[0].connection, undefined);
	assert.equal(cameraSetupStatus(unchecked, camera.id).pictureVerifiedAt, undefined);
});

test('changing archive destinations invalidates its proof and rejects an obsolete in-flight check', async (t) => {
	const { files, store } = await fixture(t);
	const camera = await readyCamera(store);
	await store.finishSetup(async () => new Set([camera.id]));
	const document = await store.read();
	const { signature } = cameraArchiveSelection(document, camera.id);
	document.config.detectors[0].exporters!.disk = [{ directory: 'other-location' }];
	await store.saveDetector({
		original: document.app.detectors[0].label,
		meta: document.app.detectors[0],
		detector: document.config.detectors[0]
	});
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
	await store.finishSetup(async () => new Set([camera.id]));
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
	const finish = queued.finishSetup(async () => {
		callbackCalled = true;
		return new Set(monitoring ? [camera.id] : []);
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
	// Match the callback-based realpath used by write-file-atomic, including Windows casing.
	const destination = await promisify(fs.realpath)(files.app);
	const rename = fs.rename;
	const failure = Object.assign(new Error('Settings are not writable'), { code: 'EACCES' });
	const blocked = t.mock.method(fs, 'rename', (...args: Parameters<typeof fs.rename>) => {
		if (String(args[1]) === destination) return args[2](failure);
		return rename(...args);
	});
	await assert.rejects(
		store.finishSetup(async () => new Set([camera.id])),
		(error) => error === failure
	);
	assert.equal(await readFile(files.app, 'utf8'), before);
	assert.equal(cameraSetupStatus(await store.read(), camera.id).completedAt, undefined);
	blocked.mock.restore();
	await store.finishSetup(async () => new Set([camera.id]));
	assert.ok(cameraSetupStatus(await store.read(), camera.id).completedAt);
});

test('client camera input cannot forge progress and rejects secrets in reusable connection metadata', () => {
	const input = { label: 'Yard', source, connection };
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
});

test('camera edits and completion do not depend on preset files', async (t) => {
	const { files, store } = await fixture(t);
	const camera = await readyCamera(store);
	await store.finishSetup(async () => new Set([camera.id]));
	const original = await store.read();
	const reopened = new ConfigurationStore(files);
	await reopened.saveCamera({ id: camera.id, label: 'Main entrance', source });
	const saved = await reopened.read();
	assert.deepEqual(saved.config.detectors, original.config.detectors);
	assert.equal(
		cameraSetupStatus(saved, camera.id).completedAt,
		cameraSetupStatus(original, camera.id).completedAt
	);
});

import { addMonitoredCamera, settingsStore } from './support/configuration.ts';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import * as v from 'valibot';
import { ConfigurationStore } from '../src/lib/server/configuration/store.ts';
import { alertsInput } from '../src/lib/configuration.ts';
import { writeJson } from '../src/lib/server/json-file.ts';

const first = 'rtsp://first.example.test/live';
const second = 'rtsp://second.example.test/live';

test('legacy identities are stable across reads, persistence, rename and password change', async (t) => {
	const { files, store } = await settingsStore(t);
	await writeJson(files.config, { detectors: [{ detection: { source: first } }] });
	const original = (await store.read()).app.streams[0].id;
	assert.equal((await new ConfigurationStore(files).read()).app.streams[0].id, original);
	await store.saveCamera({
		id: original,
		label: 'New name',
		source: 'rtsp://user:changed@first.example.test/live'
	});
	const reopened = await new ConfigurationStore(files).read();
	assert.equal(reopened.app.streams[0].id, original);
	assert.deepEqual(reopened.config.detectors[0].detection.source, [
		'rtsp://user:changed@first.example.test/live'
	]);
	assert.equal(JSON.parse(await readFile(files.app, 'utf8')).streams[0].id, original);
});

test('alerts belong to selected detectors without splitting cameras or changing other settings', async (t) => {
	const { files, store } = await settingsStore(t);
	await writeJson(files.config, {
		detectors: [
			{
				detection: { source: [first, second], interval: 2 },
				yolo: { model: 'calving.pt', confidence: 0.8 },
				exporters: { disk: {}, webhook: { url: 'https://example.test/events' } }
			},
			{ detection: { source: [first] }, yolo: { model: 'mounting.pt' }, exporters: { disk: {} } }
		]
	});
	await writeJson(files.app, { detectors: [{ label: 'Calving' }, { label: 'Mounting' }] });
	const before = await store.read();
	await store.saveAlerts({
		label: 'Phone',
		token: 'token',
		chat: 'chat',
		detectorLabels: ['Calving'],
		received: true
	});
	const saved = await store.read();
	assert.equal(saved.config.detectors.length, 2);
	assert.deepEqual(saved.app.detectors, before.app.detectors);
	assert.deepEqual(saved.app.streams, before.app.streams);
	assert.deepEqual(saved.config.detectors[0], {
		...before.config.detectors[0],
		exporters: {
			...before.config.detectors[0].exporters,
			telegram: [{ token: 'token', chat: 'chat' }]
		}
	});
	assert.deepEqual(saved.config.detectors[1], before.config.detectors[1]);
});

test('recipient edits preserve per-detector delivery options and all camera assignments', async (t) => {
	const { files, store } = await settingsStore(t);
	const channel = { token: 'old', chat: 'old-chat', alert_every: 3, include_video: false };
	const other = { token: 'other', chat: 'other-chat' };
	await writeJson(files.config, {
		detectors: [
			{
				detection: { source: [first, second] },
				yolo: { model: 'calving.pt' },
				exporters: { disk: {}, telegram: [channel, other] }
			},
			{
				detection: { source: [first] },
				yolo: { model: 'mounting.pt' },
				exporters: { disk: {}, telegram: channel }
			},
			{ detection: { source: [second] }, exporters: { disk: {} } }
		]
	});
	await writeJson(files.app, {
		detectors: [{ label: 'Calving' }, { label: 'Mounting' }, { label: 'Snapshots' }],
		telegrams: [{ label: 'Phone', ...channel }]
	});
	const before = await store.read();
	await store.saveAlerts({
		original: 'Phone',
		label: 'New phone',
		token: 'new',
		chat: 'new-chat',
		detectorLabels: ['Calving', 'Snapshots'],
		received: true
	});
	const saved = await store.read();
	assert.deepEqual(saved.app.detectors, before.app.detectors);
	assert.deepEqual(saved.app.streams, before.app.streams);
	assert.deepEqual(
		saved.config.detectors.map(({ detection, yolo, vlm }) => ({ detection, yolo, vlm })),
		before.config.detectors.map(({ detection, yolo, vlm }) => ({ detection, yolo, vlm }))
	);
	assert.deepEqual(saved.config.detectors[0].exporters, {
		...before.config.detectors[0].exporters,
		telegram: [{ ...channel, token: 'new', chat: 'new-chat' }, other]
	});
	assert.deepEqual(saved.config.detectors[1].exporters, {
		...before.config.detectors[1].exporters,
		telegram: []
	});
	assert.deepEqual(saved.config.detectors[2].exporters, {
		...before.config.detectors[2].exporters,
		telegram: [{ token: 'new', chat: 'new-chat' }]
	});
});

test('renaming an unchanged recipient leaves config.json byte-for-byte unchanged', async (t) => {
	const { files, store } = await settingsStore(t);
	await writeJson(files.config, {
		detectors: [
			{
				detection: { source: [first, second] },
				exporters: { telegram: { token: 'token', chat: 'chat', alert_every: 3 } }
			},
			{ detection: { source: first }, yolo: { model: 'other.pt' }, exporters: { disk: {} } }
		]
	});
	await writeJson(files.app, {
		detectors: [{ label: 'Calving' }, { label: 'Mounting' }],
		telegrams: [{ label: 'Phone', token: 'token', chat: 'chat' }]
	});
	const configBefore = await readFile(files.config, 'utf8');
	await store.saveAlerts({
		original: 'Phone',
		label: 'Farm phone',
		token: 'token',
		chat: 'chat',
		detectorLabels: ['Calving'],
		received: false
	});
	assert.equal(await readFile(files.config, 'utf8'), configBefore);
	assert.equal((await store.read()).app.telegrams[0].label, 'Farm phone');
});

test('unconfirmed connections and missing detectors cannot change settings', async (t) => {
	const { files, store } = await settingsStore(t);
	await addMonitoredCamera(store, { label: 'Pen', source: first }, 'calving-catcher');
	const channel = { label: 'Phone', token: 'token', chat: 'chat', detectorLabels: ['Pen'] };
	const unconfirmed = v.parse(alertsInput, { ...channel, received: false });
	await assert.rejects(store.saveAlerts(unconfirmed), /Confirm that you received/);
	await store.saveAlerts({ ...channel, received: true });
	const before = await Promise.all([readFile(files.config, 'utf8'), readFile(files.app, 'utf8')]);
	for (const edit of [
		{ ...channel, label: 'Other phone', token: 'other-token' },
		{ ...channel, original: 'Phone', token: 'changed-token' },
		{ ...channel, original: 'Phone', chat: 'changed-chat' }
	])
		await assert.rejects(
			store.saveAlerts({ ...edit, received: false }),
			/Confirm that you received/
		);
	await assert.rejects(
		store.saveAlerts({
			...channel,
			original: 'Phone',
			detectorLabels: ['missing'],
			received: false
		}),
		/no longer exists/
	);
	assert.deepEqual(
		await Promise.all([readFile(files.config, 'utf8'), readFile(files.app, 'utf8')]),
		before
	);
	await store.saveAlerts({ ...channel, original: 'Phone', token: 'changed-token', received: true });
	assert.equal(
		(await store.read()).config.detectors[0].exporters?.telegram?.[0].token,
		'changed-token'
	);
});

test('quiet hours belong to a recipient and reach every detector that alerts it', async (t) => {
	const { store } = await settingsStore(t);
	await addMonitoredCamera(store, { label: 'Pen', source: first }, 'calving-catcher');
	const channel = { label: 'Phone', token: 'token', chat: 'chat', detectorLabels: ['Pen'] };
	const quiet = { start: '22:00', end: '06:00' };
	await store.saveAlerts({ ...channel, quiet, received: true });
	let saved = await store.read();
	assert.deepEqual(saved.app.telegrams[0].quiet, quiet);
	assert.deepEqual(saved.config.detectors[0].exporters?.telegram, [
		{ token: 'token', chat: 'chat', quiet }
	]);

	// Clearing the times gives sound at any hour again.
	await store.saveAlerts({ ...channel, original: 'Phone', received: false });
	saved = await store.read();
	assert.equal(saved.app.telegrams[0].quiet, undefined);
	assert.deepEqual(saved.config.detectors[0].exporters?.telegram, [
		{ token: 'token', chat: 'chat' }
	]);
	assert.throws(() =>
		v.parse(alertsInput, { ...channel, quiet: { start: '25:00', end: '06:00' } })
	);
});

test('removing a camera removes its rules but preserves other cameras and archived data', async (t) => {
	const { files, store } = await settingsStore(t);
	const one = await addMonitoredCamera(store, { label: 'One', source: first }, 'general');
	await addMonitoredCamera(store, { label: 'Two', source: second }, 'general');
	const archiveMarker = path.join(path.dirname(files.config), 'recording.json');
	await writeJson(archiveMarker, { existing: true });
	await store.removeCamera(one.id);
	const saved = await store.read();
	assert.deepEqual(
		saved.config.detectors.map((detector) => detector.detection.source),
		[[second]]
	);
	assert.equal(saved.app.streams.length, 1);
	assert.deepEqual(JSON.parse(await readFile(archiveMarker, 'utf8')), { existing: true });
});

test('a recipient can be connected before detectors exist and later disconnected from alerts without deleting it', async (t) => {
	const { store } = await settingsStore(t);
	const recipient = { label: 'My phone', token: 'token', chat: 'chat' };
	await store.saveAlerts({ ...recipient, detectorLabels: [], received: true });
	assert.deepEqual((await store.read()).app.telegrams, [recipient]);
	await addMonitoredCamera(store, { label: 'Pen', source: first }, 'calving-catcher');
	await store.saveAlerts({
		...recipient,
		original: recipient.label,
		detectorLabels: ['Pen'],
		received: false
	});
	assert.equal((await store.read()).config.detectors[0].exporters?.telegram?.length, 1);
	await store.saveAlerts({
		...recipient,
		original: recipient.label,
		detectorLabels: [],
		received: false
	});
	const saved = await store.read();
	assert.deepEqual(saved.app.telegrams, [recipient]);
	assert.deepEqual(saved.config.detectors[0].exporters?.telegram, []);
});

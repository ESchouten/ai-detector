import { readTestPresets } from './support/presets.ts';
import assert from 'node:assert/strict';
import { test, type TestContext } from 'node:test';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import * as v from 'valibot';
import { ConfigurationStore } from '../src/lib/server/configuration/store.ts';
import { alertsInput, cameraInput } from '../src/lib/configuration.ts';
import { saveCamera as saveCameraDocument } from '../src/lib/server/configuration/cameras.ts';
import { writeJson } from '../src/lib/server/json-file.ts';
import { loadPresets } from '../src/lib/server/configuration/preset-files.ts';
import type { DetectorPreset } from '../src/lib/schema.ts';

async function fixture(t: TestContext) {
	const directory = await mkdtemp(path.join(tmpdir(), 'camera-setup-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	const files = {
		config: path.join(directory, 'config.json'),
		app: path.join(directory, 'app.json')
	};
	return { files, store: new ConfigurationStore(files, readTestPresets) };
}
const first = 'rtsp://first.example.test/live';
const second = 'rtsp://second.example.test/live';

test('first and additional cameras are assigned actual monitoring rules; view-only is explicit', async (t) => {
	const { store } = await fixture(t);
	const one = await store.saveCamera({
		label: 'Calving pen',
		source: first,
		mode: 'preset',
		preset: 'calving-catcher'
	});
	const two = await store.saveCamera({
		label: 'Yard',
		source: second,
		mode: 'preset',
		preset: 'general'
	});
	const view = await store.saveCamera({
		label: 'Gate',
		source: 'rtsp://gate.example.test/live',
		mode: 'view-only'
	});
	assert.equal(one.monitored, true);
	assert.equal(two.monitored, true);
	assert.equal(view.monitored, false);
	const saved = await store.read();
	assert.deepEqual(
		saved.config.detectors.map((detector) => detector.detection.source),
		[[first], [second]]
	);
	assert.equal(saved.app.streams.length, 3);
	assert.equal(saved.app.detectors[0].cameraId, one.id);
	assert.ok(saved.config.detectors.every((detector) => detector.exporters?.disk?.length));
});

test('copying requires an existing camera choice instead of a preset and only applies to new cameras', () => {
	const input = { label: 'Second pen', source: second };
	assert.equal(
		v.safeParse(cameraInput, { ...input, mode: 'copy', copyFromCameraId: 'pen' }).success,
		true
	);
	assert.equal(
		v.safeParse(cameraInput, { ...input, mode: 'preset', preset: 'calving-catcher' }).success,
		true
	);
	for (const selection of [
		{ mode: 'copy' },
		{ mode: 'copy', copyFromCameraId: '' },
		{ mode: 'preset', preset: 'general', copyFromCameraId: 'pen' },
		{ mode: 'view-only', copyFromCameraId: 'pen' },
		{ mode: 'copy', copyFromCameraId: 'pen', id: 'existing' }
	])
		assert.equal(v.safeParse(cameraInput, { ...input, ...selection }).success, false);
});

test('copying preserves every matching rule, model and delivery setting without changing shared cameras', async (t) => {
	const { files, store } = await fixture(t);
	await writeJson(files.config, {
		detectors: [
			{
				detection: { source: [first, second], interval: 2 },
				yolo: { model: 'models/barn.onnx', confidence: { cow: 0.71 }, frames_min: 5 },
				exporters: {
					disk: { directory: 'custom-recordings' },
					telegram: {
						token: 'farm-token',
						chat: 'farm-chat',
						include_video: false,
						alert_every: 3
					},
					webhook: { url: 'https://alerts.example.test/events' }
				}
			},
			{
				detection: { source: [first] },
				yolo: { model: 'yolo11n.pt', confidence: 0.8 },
				exporters: { disk: {}, telegram: { token: 'other-token', chat: 'other-chat' } }
			},
			{ detection: { source: [second] }, exporters: { disk: {} } }
		]
	});
	await writeJson(files.app, {
		detectors: [
			{ label: 'Barn animals', preset: 'general' },
			{ label: 'After-hours activity' },
			{ label: 'Yard' }
		]
	});
	const original = await store.read();
	const third = 'rtsp://third.example.test/live';
	const added = await store.saveCamera({
		label: 'Second barn',
		source: third,
		mode: 'copy',
		copyFromCameraId: original.app.streams[0].id!
	});
	const saved = await store.read();
	assert.equal(added.monitored, true);
	assert.deepEqual(saved.config.detectors.slice(0, 3), original.config.detectors);
	assert.deepEqual(saved.app.detectors.slice(0, 3), original.app.detectors);
	assert.deepEqual(
		saved.config.detectors.slice(3),
		original.config.detectors.slice(0, 2).map((detector) => ({
			...detector,
			detection: { ...detector.detection, source: [third] }
		}))
	);
	assert.deepEqual(saved.app.detectors.slice(3), [
		{ label: 'Second barn — Barn animals', preset: 'general', cameraId: added.id },
		{ label: 'Second barn — After-hours activity', cameraId: added.id }
	]);
	assert.deepEqual(saved.app.telegrams, original.app.telegrams);
});

test('copied rules own their nested settings so later changes cannot mutate the original', async (t) => {
	const { store } = await fixture(t);
	const firstCamera = await store.saveCamera({
		label: 'First pen',
		source: first,
		mode: 'preset',
		preset: 'calving-catcher'
	});
	await store.saveAlerts({
		label: 'Phone',
		token: 'token',
		chat: 'chat',
		detectorLabels: ['First pen'],
		received: true
	});
	const document = await store.read();
	const original = structuredClone(document.config.detectors[0]);
	saveCameraDocument(document, {
		label: 'Second pen',
		source: second,
		mode: 'copy',
		copyFromCameraId: firstCamera.id
	});
	const copied = document.config.detectors[1];
	copied.detection.source.push('rtsp://extra.example.test/live');
	copied.yolo!.model = 'custom.pt';
	copied.exporters!.telegram![0].token = 'replacement';
	assert.deepEqual(document.config.detectors[0], original);
});

test('missing and view-only cameras cannot silently provide empty monitoring settings', async (t) => {
	const { files, store } = await fixture(t);
	const camera = await store.saveCamera({ label: 'Gate', source: first, mode: 'view-only' });
	const before = await Promise.all([readFile(files.config, 'utf8'), readFile(files.app, 'utf8')]);
	for (const [copyFromCameraId, message] of [
		[camera.id, /view only/],
		['missing', /no longer exists/]
	] as const) {
		await assert.rejects(
			store.saveCamera({ label: 'Second gate', source: second, mode: 'copy', copyFromCameraId }),
			message
		);
	}
	assert.deepEqual(
		await Promise.all([readFile(files.config, 'utf8'), readFile(files.app, 'utf8')]),
		before
	);
});

test('legacy identities are stable across reads, persistence, rename and password change', async (t) => {
	const { files, store } = await fixture(t);
	await writeJson(files.config, { detectors: [{ detection: { source: first } }] });
	const original = (await store.read()).app.streams[0].id;
	assert.equal(
		(await new ConfigurationStore(files, readTestPresets).read()).app.streams[0].id,
		original
	);
	await store.saveCamera({
		id: original,
		label: 'New name',
		source: 'rtsp://user:changed@first.example.test/live',
		mode: 'keep'
	});
	const reopened = await new ConfigurationStore(files, readTestPresets).read();
	assert.equal(reopened.app.streams[0].id, original);
	assert.deepEqual(reopened.config.detectors[0].detection.source, [
		'rtsp://user:changed@first.example.test/live'
	]);
	assert.equal(JSON.parse(await readFile(files.app, 'utf8')).streams[0].id, original);
});

test('changing a watched event preserves alert options and another camera sharing the old rule', async (t) => {
	const { files, store } = await fixture(t);
	const channel = { token: 'token', chat: 'chat', include_video: false };
	await writeJson(files.config, {
		detectors: [{ detection: { source: [first, second] }, exporters: { telegram: channel } }]
	});
	const camera = (await store.read()).app.streams[0];
	await store.saveCamera({
		id: camera.id,
		label: 'Calving pen',
		source: first,
		mode: 'preset',
		preset: 'calving-catcher'
	});
	const saved = await store.read();
	assert.deepEqual(saved.config.detectors[0].detection.source, [second]);
	assert.deepEqual(saved.config.detectors[1].detection.source, [first]);
	assert.deepEqual(saved.config.detectors[1].exporters?.telegram, [channel]);
});

test('alerts belong to selected detectors without splitting cameras or changing other settings', async (t) => {
	const { files, store } = await fixture(t);
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
	const { files, store } = await fixture(t);
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
	const { files, store } = await fixture(t);
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

test('unconfirmed connections and missing detector selections cannot change settings', async (t) => {
	const { files, store } = await fixture(t);
	await store.saveCamera({
		label: 'Pen',
		source: first,
		mode: 'preset',
		preset: 'calving-catcher'
	});
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
		store.saveAlerts({ ...channel, original: 'Phone', detectorLabels: [], received: false }),
		/Choose at least one detector/
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

test('removing a camera removes its rules but preserves other cameras and archived data', async (t) => {
	const { files, store } = await fixture(t);
	const one = await store.saveCamera({
		label: 'One',
		source: first,
		mode: 'preset',
		preset: 'general'
	});
	await store.saveCamera({ label: 'Two', source: second, mode: 'preset', preset: 'general' });
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

test('local preset files reload edited templates without changing existing cameras', async (t) => {
	const { files } = await fixture(t);
	const directory = path.join(path.dirname(files.app), 'presets');
	const templateFile = path.join(directory, 'keep.json');
	await writeJson(templateFile, {
		detection: { interval: 2 },
		yolo: { model: 'workshop.onnx', confidence: { person: 0.75, forklift: 0.65 }, frames_min: 7 },
		exporters: { disk: { directory: 'workshop-recordings' } }
	});
	const store = new ConfigurationStore(files, () => loadPresets(directory));
	const one = await store.saveCamera({
		label: 'Loading area',
		source: first,
		mode: 'preset',
		preset: 'keep'
	});
	const original = (await store.read()).config.detectors[0];
	assert.equal(one.monitored, true);
	assert.deepEqual(original, {
		detection: { source: [first], interval: 2 },
		yolo: { model: 'workshop.onnx', confidence: { person: 0.75, forklift: 0.65 }, frames_min: 7 },
		exporters: { disk: [{ directory: 'workshop-recordings' }] }
	});
	await writeJson(templateFile, {
		yolo: { model: 'workshop-v2.pt' },
		exporters: { disk: { directory: 'workshop-v2' } }
	});
	await store.saveCamera({ label: 'Work bench', source: second, mode: 'preset', preset: 'keep' });
	const saved = await store.read();
	assert.deepEqual(saved.config.detectors[0], original);
	assert.equal(saved.config.detectors[1].yolo?.model, 'workshop-v2.pt');
	assert.deepEqual(saved.config.detectors[1].detection.source, [second]);
	assert.deepEqual(
		saved.app.detectors.map((meta) => meta.preset),
		['keep', 'keep']
	);
	assert.deepEqual((await loadPresets(directory))[0].detector.detection.source, []);
});

test('arbitrary preset IDs do not collide with camera actions and templates are not mutated', async (t) => {
	const { files } = await fixture(t);
	const presets: DetectorPreset[] = ['keep', 'copy', 'view-only'].map((id) => ({
		id,
		name: id,
		detector: {
			detection: { source: [] },
			yolo: { model: 'security.pt' },
			exporters: { disk: [{}] }
		}
	}));
	const before = structuredClone(presets);
	const store = new ConfigurationStore(files, async () => presets);
	for (const preset of presets) {
		const input = v.parse(cameraInput, {
			mode: 'preset',
			preset: preset.id,
			source: `rtsp://${preset.id}.example.test/live`,
			label: preset.name
		});
		assert.equal((await store.saveCamera(input)).monitored, true);
	}
	assert.deepEqual(presets, before);
	assert.equal((await store.read()).config.detectors.length, 3);
});

test('unknown preset IDs reject saves without changing either settings file', async (t) => {
	const { files, store } = await fixture(t);
	const camera = await store.saveCamera({
		label: 'Yard',
		source: first,
		mode: 'preset',
		preset: 'general'
	});
	const before = await Promise.all([readFile(files.config, 'utf8'), readFile(files.app, 'utf8')]);
	for (const input of [
		{ label: 'Another camera', source: second },
		{ id: camera.id, label: 'Renamed camera', source: first }
	])
		await assert.rejects(
			store.saveCamera({ ...input, mode: 'preset', preset: 'removed-preset' }),
			/no longer available/
		);
	assert.deepEqual(
		await Promise.all([readFile(files.config, 'utf8'), readFile(files.app, 'utf8')]),
		before
	);
});

test('changing to a custom preset preserves existing alert and recording destinations', async (t) => {
	const { files, store } = await fixture(t);
	const camera = await store.saveCamera({
		label: 'Entrance',
		source: first,
		mode: 'preset',
		preset: 'general'
	});
	await store.saveAlerts({
		label: 'Security desk',
		token: 'token',
		chat: 'chat',
		detectorLabels: ['Entrance'],
		received: true
	});
	const previous = (await store.read()).config.detectors[0].exporters;
	const custom = new ConfigurationStore(files, async () => [
		{
			id: 'intrusion',
			name: 'Restricted area',
			detector: {
				detection: { source: [], interval: 1 },
				yolo: { model: 'intrusion.onnx', confidence: { person: 0.8 } },
				exporters: { disk: [{ directory: 'new-default' }] }
			}
		}
	]);
	await custom.saveCamera({
		id: camera.id,
		label: 'Entrance',
		source: first,
		mode: 'preset',
		preset: 'intrusion'
	});
	const saved = await custom.read();
	assert.equal(saved.config.detectors[0].yolo?.model, 'intrusion.onnx');
	assert.deepEqual(saved.config.detectors[0].exporters, previous);
	assert.equal(saved.app.detectors[0].preset, 'intrusion');
});

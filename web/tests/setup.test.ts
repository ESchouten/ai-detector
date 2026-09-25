import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { setupStep } from '../src/lib/setup.ts';
import { ConfigurationStore } from '../src/lib/server/configuration/store.ts';
import { applyDetectorPreset, createDetectorDraft } from '../src/lib/detector-editor.ts';
import { readTestPresets } from './support/presets.ts';

test('setup resumes from saved configuration and always connects cameras first', () => {
	for (const requested of [null, 'cameras', 'detectors', 'finish', 'unknown'])
		assert.equal(setupStep(requested, 0, 0), 'cameras');
	assert.equal(setupStep(null, 2, 0), 'detectors');
	assert.equal(setupStep(null, 2, 1), 'finish');
	assert.equal(setupStep('cameras', 2, 1), 'cameras');
	assert.equal(setupStep('detectors', 2, 1), 'detectors');
	assert.equal(setupStep('finish', 2, 0), 'finish');
});

test('cameras are saved first, shared by detectors later, and stay assigned after reconnecting', async (t) => {
	const directory = await mkdtemp(path.join(tmpdir(), 'setup-stages-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	const files = {
		config: path.join(directory, 'config.json'),
		app: path.join(directory, 'app.json')
	};
	const store = new ConfigurationStore(files, readTestPresets);
	const entrance = 'rtsp://camera-one.example.test/live';
	const yard = 'rtsp://camera-two.example.test/live';
	const one = await store.saveCamera({ label: 'Entrance', source: entrance, mode: 'view-only' });
	await store.saveCamera({ label: 'Yard', source: yard, mode: 'view-only' });
	let saved = await new ConfigurationStore(files, readTestPresets).read();
	assert.equal(saved.app.streams.length, 2);
	assert.deepEqual(saved.config.detectors, []);
	assert.deepEqual(saved.app.detectors, []);
	const preset = (await readTestPresets()).find((item) => item.id === 'general')!;
	const draft = createDetectorDraft();
	draft.detection.source = [entrance, yard];
	const first = applyDetectorPreset(draft, preset.detector, { keepDelivery: false });
	await store.saveDetector({ meta: { label: 'General activity' }, detector: first });
	const second = createDetectorDraft(first);
	second.detection.source = [yard];
	second.detection.interval = 3;
	await store.saveDetector({ meta: { label: 'Yard activity' }, detector: second });
	const updatedSource = 'rtsp://camera-one.example.test/new-stream';
	await store.saveCamera({
		id: one.id,
		label: 'Front entrance',
		source: updatedSource,
		mode: 'keep'
	});
	saved = await new ConfigurationStore(files, readTestPresets).read();
	assert.deepEqual(
		saved.config.detectors.map((detector) => detector.detection.source),
		[[updatedSource, yard], [yard]]
	);
	assert.deepEqual(saved.config.detectors[0].exporters, first.exporters);
	assert.deepEqual(saved.config.detectors[1], second);
	assert.equal(saved.app.streams[0].id, one.id);
	assert.equal(saved.app.streams[0].label, 'Front entrance');
	assert.equal(saved.app.streams.length, 2);
});

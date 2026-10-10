import assert from 'node:assert/strict';
import { test } from 'node:test';
import { setupStep } from '../src/lib/setup.ts';
import { ConfigurationStore } from '../src/lib/server/configuration/store.ts';
import { applyDetectorPreset, createDetectorDraft } from '../src/lib/detector-editor.ts';
import { settingsStore } from './support/configuration.ts';
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
	const { files, store } = await settingsStore(t);
	const entrance = 'rtsp://camera-one.example.test/live';
	const yard = 'rtsp://camera-two.example.test/live';
	const one = await store.saveCamera({ label: 'Entrance', source: entrance });
	await store.saveCamera({ label: 'Yard', source: yard });
	let saved = await new ConfigurationStore(files).read();
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
		source: updatedSource
	});
	saved = await new ConfigurationStore(files).read();
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

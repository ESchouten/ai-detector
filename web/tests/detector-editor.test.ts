import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
	applyDetectorPreset,
	cameraRuleNames,
	createDetectorDraft,
	validDetectorDraft,
	selectTelegram
} from '../src/lib/detector-editor.ts';
import type { DetectorConfig, TelegramConfig } from '../src/lib/schema.ts';

test('camera rule names use preset filenames and preserve removed or custom rule labels', () => {
	const rules = [
		{ label: 'Saved entrance rule', preset: 'entry' },
		{ label: 'Legacy delivery rule', preset: 'removed' },
		{ label: 'Custom rule' }
	];
	const presets = [{ id: 'entry', name: 'Entry' }];
	assert.equal(cameraRuleNames(rules, presets), 'Entry, Legacy delivery rule, Custom rule');
	assert.equal(
		cameraRuleNames(rules, []),
		'Saved entrance rule, Legacy delivery rule, Custom rule'
	);
});

for (const yolo of [undefined, null]) {
	test(`opening a snapshot detector preserves yolo=${String(yolo)} and isolates edits`, () => {
		const saved: DetectorConfig = {
			detection: { source: ['camera.mp4'], interval: 2 },
			...(yolo === null ? { yolo } : {}),
			exporters: { disk: [{ strategy: 'ALL' }] }
		};
		const draft = createDetectorDraft(saved);
		assert.deepEqual(draft, saved);
		draft.detection.source.push('second.mp4');
		assert.deepEqual(saved.detection.source, ['camera.mp4']);
		assert.equal('yolo' in draft, yolo === null);
	});
}

test('advanced configuration normalizes scalar inputs without inventing detection or losing options', () => {
	const input = {
		detection: { source: 'camera.mp4' },
		// The editor leaves this key behind when verification is switched off.
		vlm: undefined,
		exporters: {
			telegram: { token: 'private-token', chat: 'alerts', include_video: false, alert_every: 4 }
		}
	};
	const before = structuredClone(input);
	const draft = validDetectorDraft(input);
	assert.deepEqual(input, before);
	assert.equal('vlm' in draft, false);
	assert.deepEqual(draft.detection.source, ['camera.mp4']);
	assert.equal('yolo' in draft, false);
	assert.deepEqual(draft.exporters.telegram, [
		{ token: 'private-token', chat: 'alerts', include_video: false, alert_every: 4 }
	]);
});

test('incompatible shapes are rejected before saving', () => {
	for (const input of [
		null,
		[],
		{},
		{ detection: null },
		{ detection: { source: [] } },
		{ detection: { source: 'camera.mp4' }, yolo: { model: 7 } }
	]) {
		assert.throws(() => validDetectorDraft(input));
	}
});

test('selecting Telegram preserves existing options and channels absent from the saved list', () => {
	const configured: TelegramConfig = {
		token: 'token-a',
		chat: 'a',
		alert_every: 3,
		include_crop: true
	};
	const unlisted: TelegramConfig = { token: 'token-b', chat: 'b', include_video: false };
	const current = [configured, unlisted];
	const channel = { label: 'Barn', token: 'token-a', chat: 'a' };
	assert.strictEqual(selectTelegram(current, channel, true), current);
	assert.deepEqual(selectTelegram(current, channel, false), [unlisted]);
	assert.deepEqual(selectTelegram(current, { label: 'Field', token: 'token-c', chat: 'c' }, true), [
		configured,
		unlisted,
		{ token: 'token-c', chat: 'c' }
	]);
	assert.deepEqual(current, [configured, unlisted]);
});

test('new detectors receive their own source and archive settings', () => {
	const first = createDetectorDraft();
	first.detection.source.push('camera.mp4');
	const second = createDetectorDraft();
	assert.deepEqual(second.detection.source, []);
	assert.deepEqual(second.exporters.disk, [{}]);
	assert.deepEqual(second.yolo, { model: '' });
});

test('new custom detectors require an explicit model and do not invent model thresholds', () => {
	const draft = createDetectorDraft();
	draft.detection.source.push('rtsp://camera.example/entrance');
	assert.throws(() => validDetectorDraft(draft));
	draft.yolo!.model = 'custom-entrance-model.pt';
	const valid = validDetectorDraft(draft);
	// The saved copy is its own; later edits to the draft do not reach it.
	draft.detection.source.push('rtsp://camera.example/yard');
	assert.deepEqual(valid.yolo, { model: 'custom-entrance-model.pt' });
	assert.deepEqual(valid.detection.source, ['rtsp://camera.example/entrance']);
});

test('changing a preset preserves sources, notification recipients and custom delivery settings', () => {
	const saved = {
		detection: { source: ['rtsp://camera.example/live'] },
		yolo: { model: 'old.pt' },
		exporters: {
			telegram: [{ token: 'token', chat: 'chat', include_video: false }],
			disk: [{ directory: 'custom' }]
		}
	};
	const preset = {
		detection: { source: [], interval: 1 },
		yolo: { model: 'new.pt' },
		exporters: { disk: [{}] }
	};
	const updated = applyDetectorPreset(saved, preset);
	assert.deepEqual(updated.detection.source, saved.detection.source);
	assert.deepEqual(updated.exporters, saved.exporters);
	assert.equal(updated.yolo?.model, 'new.pt');
	assert.equal(updated.detection.interval, 1);
});

test('new preset detectors use preset recording defaults and keep the selected cameras', () => {
	const draft = createDetectorDraft();
	draft.detection.source = ['camera-one', 'camera-two'];
	const preset: DetectorConfig = {
		detection: { source: [], interval: 2 },
		yolo: { model: 'example.pt' },
		exporters: { disk: [{ directory: 'events', strategy: 'ALL' }] }
	};
	const result = applyDetectorPreset(draft, preset, { keepDelivery: false });
	assert.deepEqual(result.detection.source, draft.detection.source);
	assert.deepEqual(result.exporters, preset.exporters);
	result.exporters.disk![0].directory = 'changed';
	assert.equal(preset.exporters!.disk![0].directory, 'events');
});

test('changing presets keeps an explicitly paused validator paused when connections are edited later', () => {
	const current = {
		detection: { source: ['video.mp4'] },
		vlm: [{ prompt: 'Old question', model: ['gemini/first', 'gemini/backup'], key: null }]
	};
	const preset = {
		detection: { source: [] },
		vlm: [{ prompt: 'New question', strategy: 'VIDEO' as const, key: null }]
	};
	const result = applyDetectorPreset(current, preset);
	assert.deepEqual(result.vlm?.[0], {
		prompt: 'New question',
		strategy: 'VIDEO',
		key: null,
		model: current.vlm[0].model
	});
	assert.notStrictEqual(result.vlm?.[0].model, current.vlm[0].model);
	assert.equal('model' in preset.vlm[0], false);
});

import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
	applyDetectorPreset,
	cameraMonitoringChoice,
	cameraRuleNames,
	createDetectorDraft,
	parseDetectorDraft,
	selectTelegram
} from '../src/lib/detector-editor.ts';
import type { DetectorConfig, TelegramConfig } from '../src/lib/schema.ts';

test('camera rule descriptions use catalogue names and preserve removed or custom rule labels', () => {
	const rules = [
		{ label: 'Saved entrance rule', preset: 'entry' },
		{ label: 'Legacy delivery rule', preset: 'removed' },
		{ label: 'Custom rule' }
	];
	const presets = [{ id: 'entry', name: 'Entrance activity', description: 'Watch the entrance.' }];
	assert.equal(
		cameraRuleNames(rules, presets),
		'Entrance activity, Legacy delivery rule, Custom rule'
	);
	assert.equal(
		cameraRuleNames(rules, []),
		'Saved entrance rule, Legacy delivery rule, Custom rule'
	);
});

test('catalogue preset IDs do not collide with camera actions', () => {
	for (const id of ['keep', 'copy', 'view-only', 'warehouse-entrance', 'custom:delivery']) {
		assert.deepEqual(cameraMonitoringChoice(`preset:${id}`), { mode: 'preset', preset: id });
	}
	for (const mode of ['keep', 'copy', 'view-only']) {
		assert.deepEqual(cameraMonitoringChoice(mode), { mode });
	}
});

test('monitoring requires an explicit selection and accepts saved arbitrary preset IDs', () => {
	for (const selection of ['', 'preset:', 'unknown-action']) {
		assert.equal(cameraMonitoringChoice(selection), undefined);
	}
	const restored = JSON.parse(JSON.stringify({ monitoringSelection: 'preset:custom-camera-rule' }));
	assert.deepEqual(cameraMonitoringChoice(restored.monitoringSelection), {
		mode: 'preset',
		preset: 'custom-camera-rule'
	});
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
	const draft = parseDetectorDraft(
		JSON.stringify({
			detection: { source: 'camera.mp4' },
			exporters: {
				telegram: { token: 'private-token', chat: 'alerts', include_video: false, alert_every: 4 }
			}
		})
	);
	assert.deepEqual(draft.detection.source, ['camera.mp4']);
	assert.equal('yolo' in draft, false);
	assert.deepEqual(draft.exporters.telegram, [
		{ token: 'private-token', chat: 'alerts', include_video: false, alert_every: 4 }
	]);
});

test('invalid JSON and incompatible form shapes are rejected before editing', () => {
	for (const text of [
		'{',
		'null',
		'[]',
		'{}',
		'{"detection":null}',
		'{"detection":{"source":[]}}',
		'{"detection":{"source":"camera.mp4"},"yolo":{"model":7}}'
	]) {
		assert.throws(() => parseDetectorDraft(text));
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
	assert.throws(() => parseDetectorDraft(JSON.stringify(draft)));
	draft.yolo!.model = 'custom-entrance-model.pt';
	const valid = parseDetectorDraft(JSON.stringify(draft));
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

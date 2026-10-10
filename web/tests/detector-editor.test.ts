import assert from 'node:assert/strict';
import { test } from 'node:test';
import { detectorSettings } from '../src/lib/configuration.ts';
import {
	applyDetectorPreset,
	chooseConnection,
	choosePreset,
	createDetectorDraft,
	detectorChoices,
	followsPreset,
	lacksQuestion,
	questionPreset,
	restoreDetectorChoices,
	selectTelegram,
	validDetectorDraft,
	type DetectorEdit,
	type DetectorOptions
} from '../src/lib/detector-editor.ts';
import type { DetectorConfig, TelegramConfig } from '../src/lib/schema.ts';

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

const barn = { id: 'camera-barn', source: 'rtsp://farmer:secret@barn.example/live' };
const yard = { id: 'camera-yard', source: 'rtsp://farmer:secret@yard.example/live' };
const phone = { label: 'Phone', token: 'bot-token', chat: '1234' };
const gemini = { label: 'Gemini', model: 'gemini/flash', key: 'api-key' };
const calving: DetectorConfig = {
	detection: { source: [], interval: 2 },
	yolo: { model: 'calving.pt' },
	vlm: [{ prompt: 'Is a cow calving?', strategy: 'VIDEO' }],
	exporters: { disk: [{ directory: 'calving' }] }
};
const options: DetectorOptions = {
	cameras: [barn, yard],
	telegrams: [phone],
	connections: [gemini],
	presets: [
		{ id: 'calving', name: 'Calving Catcher' },
		{ id: 'general', name: 'General' }
	],
	usedLabels: ['Calving Catcher']
};
const blank = (): DetectorEdit => ({
	label: '',
	suggestedLabel: '',
	detector: createDetectorDraft(),
	preset: '',
	presetSettings: '',
	connection: ''
});
const presetDetector = async (id: string) => {
	assert.equal(id, 'calving');
	return structuredClone(calving);
};

test('a preset names an unnamed rule, connects its question when asked to, and leaves a typed name alone', () => {
	const chosen = { id: 'calving', detector: calving };
	const suggested = choosePreset(blank(), chosen, options, {
		keepDelivery: false,
		suggestConnection: true
	});
	assert.equal(suggested.label, 'Calving Catcher (2)');
	assert.equal(suggested.suggestedLabel, suggested.label);
	assert.equal(suggested.connection, 'Gemini');
	assert.equal(suggested.detector.vlm?.[0].key, 'api-key');
	assert.deepEqual(suggested.detector.exporters, calving.exporters);
	assert.ok(followsPreset(suggested.detector, suggested.presetSettings));

	const typed = choosePreset({ ...blank(), label: 'North pen' }, chosen, options, {
		keepDelivery: false,
		suggestConnection: false
	});
	assert.equal(typed.label, 'North pen');
	assert.equal(typed.connection, '');
	assert.equal(typed.detector.vlm?.[0].key, undefined);
	// Choosing again renames a suggested name, never a typed one.
	const again = choosePreset(suggested, { id: 'general', detector: calving }, options, {
		keepDelivery: true,
		suggestConnection: false
	});
	assert.equal(again.label, 'General');
});

test('an unfinished edit comes back from references alone, in the order it was made', async () => {
	const edit = blank();
	edit.detector.detection.source = [barn.source];
	const before = structuredClone(edit);
	const draft = {
		label: 'North pen',
		preset: 'calving',
		cameras: [yard.id, 'camera-removed'],
		telegrams: ['Phone', 'Removed recipient'],
		connection: 'Gemini',
		validatorEnabled: true
	};
	const { edit: restored, problem } = await restoreDetectorChoices(
		edit,
		draft,
		options,
		{ keepDelivery: false },
		presetDetector
	);
	assert.equal(problem, undefined);
	assert.deepEqual(edit, before);
	assert.equal(restored.label, 'North pen');
	assert.equal(restored.preset, 'calving');
	assert.ok(followsPreset(restored.detector, restored.presetSettings));
	assert.deepEqual(restored.detector.detection.source, [yard.source]);
	assert.deepEqual(restored.detector.exporters, {
		disk: [{ directory: 'calving' }],
		telegram: [{ token: 'bot-token', chat: '1234' }]
	});
	assert.equal(restored.connection, 'Gemini');
	assert.equal(restored.detector.vlm?.[0].prompt, 'Is a cow calving?');
	assert.equal(restored.detector.vlm?.[0].key, 'api-key');
	// What is kept in the browser names saved settings and holds none of their secrets.
	const kept = detectorChoices(restored, options);
	assert.deepEqual(kept, { ...draft, cameras: [yard.id], telegrams: ['Phone'] });
	assert.doesNotMatch(JSON.stringify(kept), /secret|bot-token|api-key|rtsp:/);
});

test('a paused validator stays paused, and a rule without recipients gains no empty list', async () => {
	const saved: DetectorEdit = {
		...blank(),
		label: 'Calving',
		detector: createDetectorDraft({ ...calving, detection: { source: [barn.source] } }),
		preset: 'calving',
		presetSettings: JSON.stringify(detectorSettings(calving))
	};
	const { edit: restored, problem } = await restoreDetectorChoices(
		saved,
		{
			label: 'Calving',
			preset: 'calving',
			cameras: [barn.id],
			telegrams: [],
			connection: 'Gemini',
			validatorEnabled: false
		},
		{ ...options, telegrams: [] },
		{ savedPreset: 'calving', keepDelivery: true },
		async () => assert.fail('The saved preset is not fetched again.')
	);
	assert.equal(problem, undefined);
	assert.equal(restored.connection, 'Gemini');
	assert.deepEqual(restored.detector.vlm?.[0].model, 'gemini/flash');
	assert.equal(restored.detector.vlm?.[0].key, null);
	assert.ok(!('telegram' in restored.detector.exporters));
});

test('a preset that cannot be fetched is reported and the other choices still return', async () => {
	const unavailable = new Error('Preset file is not valid JSON.');
	const { edit: restored, problem } = await restoreDetectorChoices(
		blank(),
		{
			label: 'North pen',
			preset: 'calving',
			cameras: [barn.id],
			telegrams: ['Phone'],
			connection: 'Gemini',
			validatorEnabled: true
		},
		options,
		{ keepDelivery: false },
		() => Promise.reject(unavailable)
	);
	assert.equal(restored.preset, '');
	assert.equal(restored.label, 'North pen');
	assert.deepEqual(restored.detector.detection.source, [barn.source]);
	assert.equal(restored.detector.exporters.telegram?.length, 1);
	// The connection is restored, but there is no question to ask without the preset.
	assert.equal(restored.connection, 'Gemini');
	assert.deepEqual(problem, { kind: 'no-question' });

	const withoutConnection = await restoreDetectorChoices(
		blank(),
		{
			label: '',
			preset: 'calving',
			cameras: [],
			telegrams: [],
			connection: '',
			validatorEnabled: false
		},
		options,
		{ keepDelivery: false },
		() => Promise.reject(unavailable)
	);
	assert.deepEqual(withoutConnection.problem, { kind: 'preset', cause: unavailable });
});

test('a connection chosen for a preset rule takes the preset’s question when the rule has none', () => {
	const edit: DetectorEdit = {
		...blank(),
		detector: createDetectorDraft({ ...calving, vlm: undefined }),
		preset: 'calving',
		presetSettings: JSON.stringify(detectorSettings(calving))
	};
	assert.equal(questionPreset(edit, options.presets), 'calving');
	const connected = chooseConnection(edit, gemini, calving);
	assert.equal(connected.connection, 'Gemini');
	assert.equal(connected.detector.vlm?.[0].prompt, 'Is a cow calving?');
	assert.equal(questionPreset(connected, options.presets), undefined);
	assert.equal(lacksQuestion(connected.detector), false);
	assert.equal(lacksQuestion(chooseConnection(blank(), gemini).detector), true);
});

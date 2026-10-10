import { awaitsConnection, suggestedConnection } from '../src/lib/llm.ts';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFile } from 'node:fs/promises';
import {
	normalizeConfiguration,
	normalizeConfig,
	detectorSettings
} from '../src/lib/configuration.ts';
import {
	assignConnection,
	clearVerificationKeys,
	connectionMatches,
	GEMINI_MODELS
} from '../src/lib/llm.ts';
import * as v from 'valibot';
import { llmConnection, type LlmConnection } from '../src/lib/schema.ts';
import { settingsStore } from './support/configuration.ts';
import { readTestPresets } from './support/presets.ts';

const connection: LlmConnection = {
	label: 'Shared AI',
	model: 'openai/vision',
	key: 'test-only',
	url: 'https://example.test/v1',
	headers: { 'X-Tenant': 'test' }
};

test('a preset can retain an inactive question; enabling it requires a model', () => {
	const template = {
		detection: { source: ['video.mp4'] },
		vlm: { key: null, prompt: 'Is an event visible?' }
	};
	assert.equal(normalizeConfig({ detectors: [template] }).detectors[0].vlm![0].key, null);
	for (const vlm of [
		{ key: 'test-only', prompt: 'Check?' },
		{ key: '', prompt: 'Check?', model: [] }
	]) {
		assert.throws(() => normalizeConfig({ detectors: [{ ...template, vlm }] }));
	}
	const active = assignConnection(
		normalizeConfig({ detectors: [template] }).detectors[0],
		connection
	);
	assert.deepEqual(
		detectorSettings(active),
		detectorSettings(normalizeConfig({ detectors: [template] }).detectors[0])
	);
});

for (const editing of [false, true]) {
	test(`${editing ? 'editing' : 'adding'} a connection activates saved preset validators waiting for one`, async (t) => {
		const { files, store } = await settingsStore(t);
		if (editing) await store.saveLlm(connection);
		const presets = (await readTestPresets()).filter(({ detector }) => detector.vlm?.length);
		assert.equal(presets.length, 3);
		for (const { id, name, detector } of presets) {
			await store.saveDetector({
				meta: { label: name, preset: id },
				detector: { ...detector, detection: { ...detector.detection, source: ['video.mp4'] } }
			});
		}
		const before = await store.read();
		for (const detector of before.config.detectors) {
			assert.equal(detector.vlm![0].key, null);
			assert.equal(detector.vlm![0].strategy, 'VIDEO');
			assert.equal(detector.vlm![0].model, undefined);
		}
		const selected = { ...connection, label: 'Configured AI', key: 'configured-key' };
		await store.saveLlm({ ...selected, ...(editing ? { original: connection.label } : {}) });
		const saved = await store.read();
		for (const [i, detector] of saved.config.detectors.entries()) {
			assert.deepEqual(detector, assignConnection(before.config.detectors[i], selected));
			assert.equal(detector.vlm![0].key, selected.key);
			assert.equal(detector.vlm![0].strategy, 'VIDEO');
			assert.equal(detector.vlm![0].prompt, presets[i].detector.vlm![0].prompt);
			assert.deepEqual(saved.app.detectors[i], {
				...before.app.detectors[i],
				llmConnection: selected.label
			});
		}
		assert.deepEqual(
			JSON.parse(await readFile(files.config, 'utf8')).detectors,
			saved.config.detectors
		);
	});
}

test('a new connection preserves paused, standalone and already assigned validators', async (t) => {
	const { store } = await settingsStore(t);
	await store.saveLlm(connection);
	const waiting = { key: null, prompt: 'Check the event?', strategy: 'VIDEO' as const };
	for (const [label, settings] of Object.entries({
		Paused: { vlm: [{ ...waiting, model: connection.model }] },
		Standalone: { vlm: [{ ...waiting, model: 'openai/custom', key: 'custom-key' }] },
		'No validator': {},
		Assigned: { vlm: [{ ...waiting, model: connection.model }] }
	})) {
		await store.saveDetector({
			meta: { label, ...(label === 'Assigned' ? { llmConnection: connection.label } : {}) },
			detector: { detection: { source: ['video.mp4'] }, ...settings }
		});
	}
	const before = await store.read();
	await store.saveLlm({ ...connection, label: 'Another AI', key: 'different-key' });
	const after = await store.read();
	assert.deepEqual(after.config, before.config);
	assert.deepEqual(after.app.detectors, before.app.detectors);
});

test('connection assignment defaults to video when no verification settings exist', () => {
	const assigned = assignConnection({ detection: { source: ['video.mp4'] } }, connection);
	assert.equal(assigned.vlm[0].strategy, 'VIDEO');
});

test('the default Gemini connection saves one verifier with an ordered model list', async (t) => {
	const { files, store } = await settingsStore(t);
	await store.saveDetector({
		meta: { label: 'Detector' },
		detector: {
			detection: { source: ['video.mp4'] },
			vlm: [{ prompt: 'Check?', key: null, strategy: 'VIDEO' }]
		}
	});
	const gemini = { label: 'Google Gemini', model: [...GEMINI_MODELS], key: 'test-key' };
	assert.ok(gemini.model.length > 1);
	await store.saveLlm(gemini);
	const saved = await store.read();
	assert.equal(saved.config.detectors[0].vlm!.length, 1);
	const [verifier] = saved.config.detectors[0].vlm!;
	assert.deepEqual(verifier.model, GEMINI_MODELS);
	assert.equal(verifier.key, gemini.key);
	assert.equal(verifier.strategy, 'VIDEO');
	assert.equal(saved.app.detectors[0].llmConnection, gemini.label);
	assert.equal(connectionMatches(verifier, gemini), true);
	assert.equal(
		connectionMatches(verifier, { ...gemini, model: [...gemini.model].reverse() }),
		false
	);
	assert.deepEqual(JSON.parse(await readFile(files.config, 'utf8')).detectors[0].vlm, [verifier]);
	await store.saveLlm({ ...gemini, original: gemini.label, key: 'replacement' });
	assert.deepEqual((await store.read()).config.detectors[0].vlm, [
		{ ...verifier, key: 'replacement' }
	]);
});

test('connections without a key leave preset questions waiting until a key is saved', async (t) => {
	const { store } = await settingsStore(t);
	await store.saveDetector({
		meta: { label: 'Waiting' },
		detector: { detection: { source: ['video.mp4'] }, vlm: [{ prompt: 'Check?', key: null }] }
	});
	const before = await store.read();
	await store.saveLlm({ ...connection, key: null });
	assert.deepEqual((await store.read()).config, before.config);
	await store.saveLlm({ ...connection, original: connection.label });
	assert.equal((await store.read()).config.detectors[0].vlm![0].key, connection.key);
});

test('one connection updates multiple detectors without changing their questions or fallbacks', async (t) => {
	const { files, store } = await settingsStore(t);
	await store.saveLlm(connection);
	const fallback = {
		prompt: 'Fallback question',
		model: 'openai/other',
		strategy: 'IMAGE' as const
	};
	for (const label of ['First', 'Second']) {
		await store.saveDetector({
			meta: { label, llmConnection: connection.label },
			detector: {
				detection: { source: ['video.mp4'] },
				vlm: [{ key: null, prompt: `Question for ${label}`, strategy: 'IMAGE' }, fallback]
			}
		});
	}
	await store.saveLlm({
		...connection,
		original: connection.label,
		label: 'Renamed AI',
		model: 'openai/new',
		key: 'changed-key'
	});
	const saved = await store.read();
	assert.deepEqual(
		saved.app.detectors.map((meta) => meta.llmConnection),
		['Renamed AI', 'Renamed AI']
	);
	for (const [index, detector] of saved.config.detectors.entries()) {
		const [first, second] = detector.vlm!;
		assert.equal(first.prompt, `Question for ${index === 0 ? 'First' : 'Second'}`);
		assert.equal(first.key, 'changed-key');
		assert.equal(first.model, 'openai/new');
		assert.equal(first.key, 'changed-key');
		assert.deepEqual(second, fallback);
	}
	await assert.rejects(store.deleteLlm('Renamed AI'), /in use/);
	const before = await readFile(files.config, 'utf8');
	await assert.rejects(store.saveLlm({ ...connection, original: 'missing' }), /no longer exists/);
	assert.equal(await readFile(files.config, 'utf8'), before);
	for (const [index, meta] of saved.app.detectors.entries()) {
		await store.saveDetector({
			original: meta.label,
			meta: { label: meta.label },
			detector: clearVerificationKeys(saved.config.detectors[index])
		});
	}
	await store.deleteLlm('Renamed AI');
	assert.deepEqual((await store.read()).app.llms, []);
});

test('editing verification JSON detaches a stale shared connection without changing that JSON', () => {
	const detector = assignConnection(
		{ detection: { source: ['video.mp4'] }, vlm: [{ prompt: 'Check?' }] },
		connection
	);
	detector.vlm[0].key = 'custom-key';
	const normalized = normalizeConfiguration(
		{ detectors: [detector] },
		{ llms: [connection], detectors: [{ label: 'Camera', llmConnection: connection.label }] }
	);
	assert.equal(normalized.app.detectors[0].llmConnection, undefined);
	assert.deepEqual(normalized.config.detectors[0].vlm, detector.vlm);
});

test('clearing keys disables all verification and connection edits do not reactivate it', async (t) => {
	const { store } = await settingsStore(t);
	await store.saveLlm(connection);
	const original = assignConnection(
		{
			detection: { source: ['video.mp4'] },
			vlm: [
				{ prompt: 'Primary question', strategy: 'VIDEO' as const },
				{ model: 'openai/backup', prompt: 'Backup question', key: 'backup-key' }
			]
		},
		connection
	);
	const paused = clearVerificationKeys(original);
	assert.deepEqual(
		paused.vlm,
		original.vlm.map((step) => ({ ...step, key: null }))
	);
	await store.saveDetector({ meta: { label: 'Paused' }, detector: paused });
	await store.saveLlm({ ...connection, original: connection.label, key: 'replacement' });
	const saved = (await store.read()).config.detectors[0];
	assert.deepEqual(saved.vlm, paused.vlm);
	assert.equal((await store.read()).app.detectors[0].llmConnection, undefined);
	const resumed = assignConnection(saved, connection);
	assert.equal(resumed.vlm[0].key, connection.key);
	assert.deepEqual(resumed.vlm.slice(1), paused.vlm!.slice(1));
});

test('assignment seeds only missing verification settings from the preset', () => {
	const current = {
		detection: { source: ['video.mp4'] },
		yolo: { model: 'custom.pt', confidence: 0.9 }
	};
	const preset = {
		detection: { source: [] },
		yolo: { model: 'preset.pt', confidence: 0.5 },
		vlm: [{ key: null, prompt: 'Is one cow mounting another?', strategy: 'IMAGE' as const }]
	};
	const assigned = assignConnection(current, connection, preset);
	assert.deepEqual(assigned.yolo, current.yolo);
	assert.deepEqual(assigned.detection, current.detection);
	assert.equal(assigned.vlm![0].prompt, preset.vlm[0].prompt);
	const customized = {
		...assigned,
		vlm: [{ ...assigned.vlm![0], prompt: 'My own question', strategy: 'VIDEO' as const }]
	};
	assert.deepEqual(assignConnection(customized, connection, preset).vlm, customized.vlm);
});

test('connections validate model names, URLs and headers with shared rules', () => {
	for (const model of [
		'',
		'   ',
		'gemini/',
		'gemini/ ',
		'vision model',
		[],
		['valid', ''],
		['invalid model']
	])
		assert.equal(v.safeParse(llmConnection, { ...connection, model }).success, false);
	assert.equal(v.safeParse(llmConnection, { ...connection, model: GEMINI_MODELS }).success, true);
	assert.equal(
		v.safeParse(llmConnection, { ...connection, url: 'ftp://example.test' }).success,
		false
	);
	for (const headers of [
		{ 'X-Key': 'a', 'x-key': 'b' },
		{ 'Bad header': 'a' },
		{ 'X-Key': 'a\r\nb' }
	])
		assert.equal(v.safeParse(llmConnection, { ...connection, headers }).success, false);
});

test('only a waiting preset with one usable connection gets a suggested validator', () => {
	const waiting = { detection: { source: [] }, vlm: [{ prompt: 'Check the event?', key: null }] };
	assert.equal(awaitsConnection(waiting), true);
	assert.equal(suggestedConnection(waiting, [connection]), connection);
	assert.equal(suggestedConnection(waiting, []), undefined);
	assert.equal(
		suggestedConnection(waiting, [connection, { ...connection, label: 'Other' }]),
		undefined
	);
	assert.equal(suggestedConnection(waiting, [{ ...connection, key: null }]), undefined);
	assert.equal(
		suggestedConnection(waiting, [{ ...connection, key: null }, connection]),
		connection
	);
	for (const detector of [
		{ detection: { source: [] } },
		{ ...waiting, vlm: [{ prompt: '  ', key: null }] },
		clearVerificationKeys(assignConnection(waiting, connection)),
		assignConnection(waiting, connection)
	])
		assert.equal(suggestedConnection(detector, [connection]), undefined);
});

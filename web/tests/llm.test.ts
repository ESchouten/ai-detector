import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import {
	normalizeConfiguration,
	normalizeConfig,
	detectorSettings
} from '../src/lib/configuration.ts';
import { assignConnection } from '../src/lib/llm.ts';
import { ConfigurationStore } from '../src/lib/server/configuration/store.ts';
import * as v from 'valibot';
import { llmConnection, type LlmConnection } from '../src/lib/schema.ts';

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
		vlm: { enabled: false, prompt: 'Is an event visible?' }
	};
	assert.equal(normalizeConfig({ detectors: [template] }).detectors[0].vlm![0].enabled, false);
	for (const vlm of [{ prompt: 'Check?' }, { enabled: true, prompt: 'Check?', model: [] }]) {
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

test('one connection updates multiple detectors without changing their questions or fallbacks', async (t) => {
	const directory = await mkdtemp(path.join(tmpdir(), 'ai-connections-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	const files = {
		config: path.join(directory, 'config.json'),
		app: path.join(directory, 'app.json')
	};
	const store = new ConfigurationStore(files, async () => []);
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
				vlm: [{ enabled: false, prompt: `Question for ${label}`, strategy: 'IMAGE' }, fallback]
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
		assert.equal(first.enabled, true);
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
			detector: {
				...saved.config.detectors[index],
				vlm_enabled: false
			}
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

test('pausing verification survives saving and shared connection edits without disabling fallbacks', async (t) => {
	const directory = await mkdtemp(path.join(tmpdir(), 'ai-verification-pause-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	const store = new ConfigurationStore(
		{ config: path.join(directory, 'config.json'), app: path.join(directory, 'app.json') },
		async () => []
	);
	await store.saveLlm(connection);
	const fallback = {
		model: 'openai/backup',
		prompt: 'Backup question',
		strategy: 'VIDEO' as const
	};
	const disabled = { ...fallback, model: 'openai/disabled', enabled: false };
	await store.saveDetector({
		meta: { label: 'Paused', llmConnection: connection.label },
		detector: {
			detection: { source: ['video.mp4'] },
			vlm_enabled: false,
			vlm: [{ prompt: 'Primary question', enabled: false }, fallback, disabled]
		}
	});
	await store.saveLlm({ ...connection, original: connection.label, key: 'replacement' });
	const saved = (await store.read()).config.detectors[0];
	assert.equal(saved.vlm_enabled, false);
	assert.deepEqual(saved.vlm!.slice(1), [fallback, disabled]);
	const resumed = { ...assignConnection(saved, connection), vlm_enabled: true };
	assert.deepEqual(resumed.vlm!.slice(1), [fallback, disabled]);
});

test('assignment seeds only missing verification settings from the preset', () => {
	const current = {
		detection: { source: ['video.mp4'] },
		yolo: { model: 'custom.pt', confidence: 0.9 }
	};
	const preset = {
		detection: { source: [] },
		yolo: { model: 'preset.pt', confidence: 0.5 },
		vlm: [{ enabled: false, prompt: 'Is one cow mounting another?', strategy: 'IMAGE' as const }]
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
	for (const model of ['', '   ', 'gemini/', 'gemini/ ', 'vision model'])
		assert.equal(v.safeParse(llmConnection, { ...connection, model }).success, false);
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

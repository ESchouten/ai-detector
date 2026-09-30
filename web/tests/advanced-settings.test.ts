import assert from 'node:assert/strict';
import { test, type TestContext } from 'node:test';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { parseSettings } from '../src/lib/advanced-settings.ts';
import { settingsRevision } from '../src/lib/server/configuration/advanced.ts';
import { ConfigurationStore } from '../src/lib/server/configuration/store.ts';
import { ManagedDetector } from '../src/lib/server/managed-detector.ts';
import { readTestPresets } from './support/presets.ts';

async function fixture(t: TestContext) {
	const directory = await mkdtemp(path.join(tmpdir(), 'advanced-settings-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	const files = {
		config: path.join(directory, 'config.json'),
		app: path.join(directory, 'app.json')
	};
	const store = new ConfigurationStore(files, readTestPresets);
	return { directory, files, store };
}

test('editor validation accepts an empty setup and checks syntax, unknown properties and bounds', () => {
	assert.deepEqual(parseSettings('config', '{"detectors":[]}'), { detectors: [] });
	assert.throws(() => parseSettings('config', '{'), SyntaxError);
	assert.throws(
		() => parseSettings('config', '{"detectors":[], "unknown":true}'),
		/unsupported property "unknown"/
	);
	assert.throws(
		() =>
			parseSettings(
				'config',
				JSON.stringify({ detectors: [{ detection: { source: 'video.mp4', interval: -1 } }] })
			),
		/\/detectors\/0\/detection\/interval/
	);
	assert.throws(() => parseSettings('connections', '[{"label":"AI"}]'), /model/);
	assert.throws(
		() => parseSettings('connections', '[{"label":"AI","model":["gemini/model"]}]'),
		/must be string/
	);
	assert.throws(() => parseSettings('runtime', '{"mode":"cpu"}'), /allowed values/);
	assert.throws(
		() => parseSettings('runtime', '{"mode":"auto","enabled":true}'),
		/unsupported property/
	);
});

test('advanced edits preserve names, camera identities and delivery; tuning clears preset identity', async (t) => {
	const { store } = await fixture(t);
	const camera = await store.saveCamera({
		label: 'Barn',
		source: 'rtsp://camera.test/live',
		mode: 'preset',
		preset: 'calving-catcher'
	});
	let saved = await store.read();
	const draft = structuredClone(saved.config);
	draft.detectors[0].exporters = { disk: [{ strategy: 'ALL' }] };
	await store.saveAdvanced('config', draft, settingsRevision(saved));
	saved = await store.read();
	assert.equal(saved.app.detectors[0].preset, 'calving-catcher');
	draft.detectors[0].detection.interval = 17;
	await store.saveAdvanced('config', draft, settingsRevision(saved));
	saved = await store.read();
	assert.equal(saved.app.detectors[0].preset, undefined);
	assert.equal(saved.app.detectors[0].label, 'Barn');
	assert.equal(saved.app.detectors[0].cameraId, camera.id);
	assert.equal(saved.app.streams[0].id, camera.id);
	assert.equal(saved.config.detectors[0].detection.interval, 17);
	assert.deepEqual(saved.config.detectors[0].exporters, { disk: [{ strategy: 'ALL' }] });
});

test('reordering and deleting detectors retains metadata of unchanged detectors', async (t) => {
	const { store } = await fixture(t);
	for (const label of ['First', 'Second', 'Third'])
		await store.saveDetector({
			meta: { label },
			detector: { detection: { source: [`${label}.mp4`] } }
		});
	const saved = await store.read();
	await store.saveAdvanced(
		'config',
		{ detectors: [saved.config.detectors[2], saved.config.detectors[0]] },
		settingsRevision(saved)
	);
	assert.deepEqual(
		(await store.read()).app.detectors.map(({ label }) => label),
		['Third', 'First']
	);
});

test('invalid and stale saves leave both files untouched', async (t) => {
	const { store, files } = await fixture(t);
	await store.saveDetector({
		meta: { label: 'First' },
		detector: { detection: { source: ['video.mp4'] } }
	});
	const saved = await store.read();
	const revision = settingsRevision(saved);
	await store.saveStream({ source: 'other.mp4', label: 'Other camera' });
	const before = await Promise.all([readFile(files.config), readFile(files.app)]);
	await assert.rejects(
		store.saveAdvanced('config', { detectors: [] }, revision),
		/Settings changed/
	);
	const currentRevision = settingsRevision(await store.read());
	await assert.rejects(
		store.saveAdvanced('config', { detectors: [], unknown: true }, currentRevision),
		/unsupported property/
	);
	await assert.rejects(
		store.saveAdvanced('connections', [{ label: 'AI', model: 'bad model' }], currentRevision),
		/model name/
	);
	assert.deepEqual(await Promise.all([readFile(files.config), readFile(files.app)]), before);
});

test('shared connection JSON propagates credentials without changing questions or fallbacks', async (t) => {
	const { store } = await fixture(t);
	const connection = {
		label: 'AI',
		model: 'openai/vision',
		key: 'old',
		url: 'https://example.test/v1'
	};
	await store.saveLlm(connection);
	const fallback = { model: 'openai/backup', prompt: 'Backup question', enabled: false };
	for (const label of ['First', 'Second'])
		await store.saveDetector({
			meta: { label, llmConnection: 'AI' },
			detector: {
				detection: { source: ['video.mp4'] },
				vlm_enabled: false,
				vlm: [{ prompt: label, enabled: false }, fallback]
			}
		});
	let saved = await store.read();
	await store.saveAdvanced(
		'connections',
		[{ ...connection, key: 'new', headers: { 'X-Tenant': 'farm' } }],
		settingsRevision(saved)
	);
	saved = await store.read();
	for (const [i, detector] of saved.config.detectors.entries()) {
		assert.equal(detector.vlm![0].key, 'new');
		assert.equal(detector.vlm![0].prompt, saved.app.detectors[i].label);
		assert.deepEqual(detector.vlm![1], fallback);
		assert.equal(detector.vlm_enabled, false);
		assert.equal(saved.app.detectors[i].llmConnection, 'AI');
	}
	await assert.rejects(store.saveAdvanced('connections', [], settingsRevision(saved)), /in use/);
	await assert.rejects(
		store.saveAdvanced('connections', [connection, connection], settingsRevision(saved)),
		/unique name/
	);
	assert.deepEqual(await store.read(), saved);
});

test('editing detector credentials detaches only that shared connection', async (t) => {
	const { store } = await fixture(t);
	await store.saveLlm({ label: 'AI', model: 'gemini/test', key: 'shared' });
	await store.saveDetector({
		meta: { label: 'Detector', llmConnection: 'AI' },
		detector: { detection: { source: ['video.mp4'] }, vlm: [{ prompt: 'Check?', enabled: false }] }
	});
	const saved = await store.read();
	const config = structuredClone(saved.config);
	config.detectors[0].vlm![0].key = 'detector-specific';
	await store.saveAdvanced('config', config, settingsRevision(saved));
	const next = await store.read();
	assert.equal(next.app.detectors[0].llmConnection, undefined);
	assert.equal(next.app.llms[0].key, 'shared');
	assert.equal(next.config.detectors[0].vlm![0].key, 'detector-specific');
});

test('runtime mode saves without enabling monitoring and rejects a stale mode', async (t) => {
	const { directory } = await fixture(t);
	const runtime = new ManagedDetector({ executable: 'unused', dataDirectory: directory });
	await runtime.setMode('native', 'auto');
	assert.deepEqual(JSON.parse(await readFile(path.join(directory, 'runtime.json'), 'utf8')), {
		mode: 'native',
		enabled: false
	});
	assert.equal(runtime.status().mode, 'native');
	assert.equal(runtime.status().phase, 'stopped');
	await assert.rejects(runtime.setMode('docker', 'auto'), /changed/);
	const reloaded = new ManagedDetector({ executable: 'unused', dataDirectory: directory });
	await reloaded.initialize();
	assert.equal(reloaded.status().mode, 'native');
	assert.equal(reloaded.status().phase, 'stopped');
});

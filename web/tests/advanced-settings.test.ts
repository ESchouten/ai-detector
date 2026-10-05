import { addMonitoredCamera } from './support/configuration.ts';
import assert from 'node:assert/strict';
import { test, type TestContext } from 'node:test';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import * as v from 'valibot';
import { parseSettings } from '../src/lib/advanced-settings.ts';
import { heartbeatInput } from '../src/lib/configuration.ts';
import { settingsRevision } from '../src/lib/server/configuration/advanced.ts';
import { ConfigurationStore } from '../src/lib/server/configuration/store.ts';
import { ManagedDetector } from '../src/lib/server/managed-detector.ts';
import { monitoringEnabled, setMonitoringEnabled } from '../src/lib/server/monitoring-flag.ts';
import { backupSettings } from '../src/lib/server/settings-backup.ts';
import { unzipSync } from 'fflate';

async function fixture(t: TestContext) {
	const directory = await mkdtemp(path.join(tmpdir(), 'advanced-settings-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	const files = {
		config: path.join(directory, 'config.json'),
		app: path.join(directory, 'app.json')
	};
	const store = new ConfigurationStore(files);
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
	assert.deepEqual(
		parseSettings('connections', '[{"label":"AI","model":["gemini/first","gemini/backup"]}]'),
		[{ label: 'AI', model: ['gemini/first', 'gemini/backup'] }]
	);
	assert.throws(() => parseSettings('connections', '[{"label":"AI","model":[]}]'), /fewer than 1/);
	assert.deepEqual(parseSettings('config', '{"detectors":[],"runtime":"docker"}'), {
		detectors: [],
		runtime: 'docker'
	});
	assert.throws(
		() => parseSettings('config', '{"detectors":[],"runtime":"cpu"}'),
		/allowed values/
	);
});

test('advanced edits preserve names, camera identities and delivery; tuning clears preset identity', async (t) => {
	const { store } = await fixture(t);
	const camera = await addMonitoredCamera(
		store,
		{ label: 'Barn', source: 'rtsp://camera.test/live' },
		'calving-catcher'
	);
	let saved = await store.read();
	const draft = structuredClone(saved.config);
	draft.detectors[0].exporters = { disk: [{ strategy: 'ALL' }] };
	await store.saveAdvanced('config', draft, settingsRevision(saved));
	saved = await store.read();
	assert.equal(saved.app.detectors[0].preset, 'calving-catcher');
	draft.detectors[0].detection.interval = 17;
	await store.saveAdvanced('config', draft, settingsRevision(saved));
	saved = await store.read();
	assert.deepEqual(saved.app.detectors[0], { label: 'Barn' });
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
	await store.saveCamera({ source: 'other.mp4', label: 'Other camera', mode: 'view-only' });
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
		model: ['openai/vision', 'openai/backup'],
		key: 'old',
		url: 'https://example.test/v1'
	};
	await store.saveLlm(connection);
	const fallback = { model: 'openai/backup', prompt: 'Backup question', key: null };
	for (const label of ['First', 'Second'])
		await store.saveDetector({
			meta: { label, llmConnection: 'AI' },
			detector: {
				detection: { source: ['video.mp4'] },
				vlm: [{ prompt: label, key: null }, fallback]
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
		detector: { detection: { source: ['video.mp4'] }, vlm: [{ prompt: 'Check?', key: null }] }
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

test('the engine choice is part of config.json and is shown without enabling monitoring', async (t) => {
	const { directory, store } = await fixture(t);
	const runtime = new ManagedDetector({ executable: 'unused', dataDirectory: directory });
	await runtime.initialize();
	assert.equal(runtime.status().mode, 'auto');
	const saved = await store.read();
	await store.saveAdvanced(
		'config',
		{ ...saved.config, runtime: 'native' },
		settingsRevision(saved)
	);
	assert.equal(
		JSON.parse(await readFile(path.join(directory, 'config.json'), 'utf8')).runtime,
		'native'
	);
	// The store asks the launcher to apply saved settings; paused monitoring stays paused.
	await runtime.apply();
	assert.equal(runtime.status().mode, 'native');
	assert.equal(runtime.status().phase, 'stopped');
	const reloaded = new ManagedDetector({ executable: 'unused', dataDirectory: directory });
	await reloaded.initialize();
	assert.equal(reloaded.status().mode, 'native');
	assert.equal(reloaded.status().phase, 'stopped');
});

test('saving settings keeps the launcher’s resume flag, which never appears in settings, backups or revisions', async (t) => {
	const { files, store } = await fixture(t);
	const source = 'rtsp://camera.example.test/barn';
	await store.saveCamera({ label: 'Barn', source, mode: 'view-only' });
	await setMonitoringEnabled(files.app, true);
	const loaded = await store.read();
	assert.equal('monitoring' in loaded.app, false);
	const revision = settingsRevision(loaded);

	// Metadata-only, two-file and device writes each replace app.json.
	await store.saveCamera({
		id: loaded.app.streams[0].id,
		label: 'Barn north',
		source,
		mode: 'keep'
	});
	assert.equal(await monitoringEnabled(files.app), true);
	await store.saveDetector({
		meta: { label: 'Activity' },
		detector: { detection: { source: [source] } }
	});
	assert.equal(await monitoringEnabled(files.app), true);
	await store.updateDevices(() => [
		{ id: 'phone', name: 'Phone', hash: 'hash', created: 1, expires: 2 }
	]);
	assert.equal(await monitoringEnabled(files.app), true);
	assert.equal((await store.readDevices()).length, 1);

	const response = await backupSettings(store, new Request('http://localhost/setup/backup'));
	const backup = unzipSync(new Uint8Array(await response.arrayBuffer()));
	assert.equal('monitoring' in JSON.parse(Buffer.from(backup['app.json']).toString()), false);
	const snapshot = JSON.parse(await readFile(`${files.config}.last-valid`, 'utf8'));
	assert.equal('monitoring' in snapshot.app, false);

	// Pausing is not a settings change: an open Advanced draft stays valid.
	const beforePause = settingsRevision(await store.read());
	await setMonitoringEnabled(files.app, false);
	assert.equal(settingsRevision(await store.read()), beforePause);
	assert.notEqual(beforePause, revision);
});

test('the launcher and the settings store can replace app.json at the same time without losing either change', async (t) => {
	const { files, store } = await fixture(t);
	const saves = Array.from({ length: 6 }, (_, index) =>
		store.saveCamera({
			label: `Camera ${index + 1}`,
			source: `rtsp://camera.example.test/${index}`,
			mode: 'view-only'
		})
	);
	const toggles = [true, false, true, false, true].map((enabled) =>
		setMonitoringEnabled(files.app, enabled)
	);
	await Promise.all([...saves, ...toggles]);
	assert.equal(await monitoringEnabled(files.app), true);
	assert.equal((await store.read()).app.streams.length, 6);
	assert.equal(JSON.parse(await readFile(files.app, 'utf8')).streams.length, 6);
});

test('the heartbeat form changes its two fields, keeps options set in Advanced, and can be turned off', async (t) => {
	const { files, store } = await fixture(t);
	await store.saveHeartbeat({ url: 'https://hc.example.test/ping/abc', interval: 120 });
	assert.deepEqual((await store.read()).config.health, {
		url: 'https://hc.example.test/ping/abc',
		interval: 120
	});
	const saved = await store.read();
	await store.saveAdvanced(
		'config',
		{ ...saved.config, health: { ...saved.config.health, method: 'POST', timeout: 3 } },
		settingsRevision(saved)
	);
	await store.saveHeartbeat({ url: 'https://hc.example.test/ping/next', interval: 60 });
	assert.deepEqual(JSON.parse(await readFile(files.config, 'utf8')).health, {
		url: 'https://hc.example.test/ping/next',
		interval: 60,
		method: 'POST',
		timeout: 3
	});
	await store.saveHeartbeat(null);
	assert.equal('health' in JSON.parse(await readFile(files.config, 'utf8')), false);
	for (const input of [
		{ url: 'ftp://hc.example.test/ping', interval: 60 },
		{ url: 'not an address', interval: 60 },
		{ url: 'https://hc.example.test/ping', interval: 0 }
	])
		assert.equal(v.safeParse(heartbeatInput, input).success, false);
	assert.equal(
		v.parse(heartbeatInput, { url: ' https://hc.example.test/ping ', interval: 60 })!.url,
		'https://hc.example.test/ping'
	);
});

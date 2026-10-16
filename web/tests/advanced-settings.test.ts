import { addMonitoredCamera, settingsStore } from './support/configuration.ts';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFile, writeFile } from 'node:fs/promises';
import * as v from 'valibot';
import { parseSettings } from '../src/lib/advanced-settings.ts';
import { heartbeatInput } from '../src/lib/configuration.ts';
import { settingsRevision } from '../src/lib/server/configuration/advanced.ts';
import {
	installationNotes,
	monitoringEnabled,
	noteOutages,
	setMonitoringEnabled
} from '../src/lib/server/installation-notes.ts';
import { backupSettings } from '../src/lib/server/settings-backup.ts';
import { unzipSync } from 'fflate';

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
	assert.deepEqual(parseSettings('config', '{"detectors":[],"onnx":{"opset":20}}'), {
		detectors: [],
		onnx: { opset: 20 }
	});
});

test('advanced edits preserve names, camera identities and delivery; tuning clears preset identity', async (t) => {
	const { store } = await settingsStore(t);
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
	const { store } = await settingsStore(t);
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
	const { store, files } = await settingsStore(t);
	await store.saveDetector({
		meta: { label: 'First' },
		detector: { detection: { source: ['video.mp4'] } }
	});
	const saved = await store.read();
	const revision = settingsRevision(saved);
	await store.saveCamera({ source: 'other.mp4', label: 'Other camera' });
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
	const connection = { label: 'AI', model: 'openai/vision' };
	await assert.rejects(
		store.saveAdvanced('connections', [connection, connection], currentRevision),
		/unique name/
	);
	assert.deepEqual(await Promise.all([readFile(files.config), readFile(files.app)]), before);
});

test('saving settings keeps the installation’s notes, which never appear in settings, backups or revisions', async (t) => {
	const { files, store } = await settingsStore(t);
	const source = 'rtsp://camera.example.test/barn';
	await store.saveCamera({ label: 'Barn', source });
	await setMonitoringEnabled(files.app, true);
	const outages = { 'camera-a': '2026-10-12T00:10:00.000Z' };
	await noteOutages(files.app, outages);
	// The desktop runtime notes a port it moved to before the settings store starts.
	const app = JSON.parse(await readFile(files.app, 'utf8'));
	await writeFile(files.app, JSON.stringify({ ...app, port: 8080 }));
	const loaded = await store.read();
	assert.equal('monitoring' in loaded.app, false);
	assert.equal('outages' in loaded.app, false);
	assert.equal('port' in loaded.app, false);
	const revision = settingsRevision(loaded);

	// Metadata-only, two-file and device writes each replace app.json.
	await store.saveCamera({
		id: loaded.app.streams[0].id,
		label: 'Barn north',
		source
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
	assert.deepEqual(await installationNotes(files.app), { monitoring: true, outages, port: 8080 });
	assert.equal((await store.readDevices()).length, 1);

	const response = await backupSettings(store, new Request('http://localhost/settings/backup'));
	const backup = unzipSync(new Uint8Array(await response.arrayBuffer()));
	const saved = JSON.parse(Buffer.from(backup['app.json']).toString());
	assert.deepEqual(
		['monitoring' in saved, 'outages' in saved, 'port' in saved],
		[false, false, false]
	);
	const snapshot = JSON.parse(await readFile(`${files.config}.last-valid`, 'utf8'));
	assert.deepEqual(
		['monitoring' in snapshot.app, 'outages' in snapshot.app, 'port' in snapshot.app],
		[false, false, false]
	);

	// Pausing is not a settings change: an open Advanced draft stays valid.
	const beforePause = settingsRevision(await store.read());
	await setMonitoringEnabled(files.app, false);
	assert.equal(settingsRevision(await store.read()), beforePause);
	assert.notEqual(beforePause, revision);
	// Nothing left to remember leaves no trace in the file.
	await noteOutages(files.app, {});
	assert.deepEqual(await installationNotes(files.app), {
		monitoring: undefined,
		outages: undefined,
		port: 8080
	});
	assert.equal('outages' in JSON.parse(await readFile(files.app, 'utf8')), false);
});

test('the launcher and the settings store can replace app.json at the same time without losing either change', async (t) => {
	const { files, store } = await settingsStore(t);
	const saves = Array.from({ length: 6 }, (_, index) =>
		store.saveCamera({
			label: `Camera ${index + 1}`,
			source: `rtsp://camera.example.test/${index}`
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
	const { files, store } = await settingsStore(t);
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

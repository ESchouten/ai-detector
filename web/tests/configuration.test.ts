import { addPresetDetector } from './support/configuration.ts';
import { readTestPresets } from './support/presets.ts';
import assert from 'node:assert/strict';
import { test, type TestContext } from 'node:test';
import fs, { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { ConfigurationStore } from '../src/lib/server/configuration/store.ts';
import { ManagedDetector } from '../src/lib/server/managed-detector.ts';
import { normalizeConfiguration, ConfigurationError } from '../src/lib/configuration.ts';
import { DEFAULT_SCHEMA_URL, type DetectorConfig, type StreamMeta } from '../src/lib/schema.ts';
import { writeJson } from '../src/lib/server/json-file.ts';
import { configurationAction } from '../src/lib/server/configuration/request.ts';
import { isHttpError } from '@sveltejs/kit';

const source = 'rtsp://camera.local/first';
const other = 'rtsp://camera.local/second';
const detector = { detection: { source: [source] } };

test('invalid settings can be recovered from the last valid pair without deleting the damaged input', async (t) => {
	const { files, store } = await fixture(t);
	const original = await store.read();
	await writeFile(files.config, '{broken');
	await assert.rejects(store.read(), SyntaxError);
	assert.equal(await store.recoveryAvailable(), true);
	await store.restore();
	assert.deepEqual(await store.read(), original);
	const saved = (await readdir(path.dirname(files.config))).find(
		(name) => name.startsWith('config.json.') && name.endsWith('.invalid')
	);
	assert.ok(saved);
	assert.equal(await readFile(path.join(path.dirname(files.config), saved), 'utf8'), '{broken');
});

async function fixture(
	t: TestContext,
	config: unknown = { detectors: [detector] },
	app: unknown = {}
) {
	const directory = await mkdtemp(path.join(tmpdir(), 'detector-config-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	const files = {
		config: path.join(directory, 'config.json'),
		app: path.join(directory, 'app.json')
	};
	await writeJson(files.config, config);
	await writeJson(files.app, app);
	return { files, store: new ConfigurationStore(files) };
}

test('missing saved settings preserve recovery across restarts, including camera metadata', async (t) => {
	for (const missing of ['config', 'app'] as const) {
		const { files, store } = await fixture(t);
		await store.saveCamera({ label: 'Barn', source: other, mode: 'view-only' });
		const original = await store.read();
		const snapshot = await readFile(`${files.config}.last-valid`, 'utf8');
		await rm(files[missing]);
		const reopened = new ConfigurationStore(files);
		await assert.rejects(reopened.read(), /settings file is missing/);
		assert.equal(await readFile(`${files.config}.last-valid`, 'utf8'), snapshot);
		assert.equal(await reopened.recoveryAvailable(), true);
		await reopened.restore();
		assert.deepEqual(await reopened.read(), original);
	}
});

test('legacy config without app metadata stays readable and recoverable', async (t) => {
	const { files, store } = await fixture(t);
	await rm(files.app);
	const original = await store.read();
	const reopened = new ConfigurationStore(files);
	assert.deepEqual(await reopened.read(), original);
	await rm(files.config);
	await assert.rejects(reopened.read(), /settings file is missing/);
	await reopened.restore();
	assert.deepEqual(await reopened.read(), original);
});

test('scalar/list input normalizes without dropping detector or exporter options', () => {
	const { config } = normalizeConfiguration(
		{
			onnx: { provider: 'CPUExecutionProvider' },
			detectors: [
				{
					detection: { source, interval: 3 },
					yolo: null,
					vlm: null,
					exporters: {
						disk: { strategy: 'ALL' },
						telegram: { token: 'token', chat: 'chat', include_video: false }
					}
				}
			]
		},
		{}
	);
	assert.deepEqual(config.detectors[0].detection, { source: [source], interval: 3 });
	assert.equal(config.detectors[0].yolo, null);
	assert.deepEqual(config.detectors[0].exporters?.disk, [{ strategy: 'ALL' }]);
	assert.equal(config.detectors[0].exporters?.telegram?.[0].include_video, false);
	assert.deepEqual(config.onnx, { provider: 'CPUExecutionProvider' });
});

test('canonical schema rejects unknown fields, invalid bounds, empty and duplicate sources', () => {
	for (const input of [
		{ detectors: [detector], unknown: true },
		{ detectors: [{ detection: { source, interval: -1 } }] },
		{ detectors: [{ detection: { source: [] } }] },
		{ detectors: [{ detection: { source: [source, source] } }] },
		{ detectors: [{ detection: { source }, yolo: { model: 'model.pt', confidence: 2 } }] },
		{ detectors: [{ detection: { source }, exporters: { unexpected: {} } }] }
	])
		assert.throws(() => normalizeConfiguration(input, {}), ConfigurationError);
});

test('invalid local configuration identifies the file and options without exposing values or rewriting it', async (t) => {
	const { files, store } = await fixture(t, {
		detectors: [
			{
				...detector,
				identity: { key: 'private-identity-key' },
				yolo: { model: 'model.pt', tracker: 'custom-private-tracker.yaml' },
				exporters: { sse: [{ token: 'private-exporter-token' }] }
			}
		]
	});
	const before = await readFile(files.config, 'utf8');
	await assert.rejects(store.read(), (error: unknown) => {
		assert.ok(error instanceof ConfigurationError);
		assert.ok(error.message.includes(files.config));
		assert.match(error.message, /detectors\/0 has unsupported property "identity"/);
		assert.match(error.message, /exporters has unsupported property "sse"/);
		assert.match(error.message, /yolo\/tracker must be one of "botsort.yaml", "bytetrack.yaml"/);
		assert.doesNotMatch(
			error.message,
			/private-identity-key|private-exporter-token|custom-private-tracker/
		);
		return true;
	});
	assert.equal(await readFile(files.config, 'utf8'), before);
});

test('source whitespace normalization preserves one camera identity and rejects normalized duplicates', () => {
	const document = normalizeConfiguration(
		{ detectors: [{ detection: { source: ` ${source} ` } }] },
		{ streams: [{ label: 'Barn', source }] }
	);
	assert.deepEqual(document.config.detectors[0].detection.source, [source]);
	assert.deepEqual(document.app.streams, [{ label: 'Barn', source }]);
	assert.deepEqual(normalizeConfiguration(document.config, document.app), document);
	assert.throws(
		() =>
			normalizeConfiguration(
				{ detectors: [{ detection: { source: [source, ` ${source} `] } }] },
				{}
			),
		/same source more than once/
	);
});

test('loaded notification identities match their exporters without silently changing credentials', () => {
	const telegram = { token: ' token ', chat: ' chat ' };
	const document = normalizeConfiguration(
		{ detectors: [{ ...detector, exporters: { telegram } }] },
		{ telegrams: [{ label: 'Farm alerts', ...telegram }] }
	);
	assert.deepEqual(document.app.telegrams, [{ label: 'Farm alerts', ...telegram }]);
	assert.deepEqual(document.config.detectors[0].exporters?.telegram, [telegram]);
});

test('expected configuration failures reach the UI as actionable client errors', async () => {
	await assert.rejects(
		configurationAction(Promise.reject(new ConfigurationError('This detector no longer exists.'))),
		(failure) => {
			assert.ok(isHttpError(failure, 400));
			assert.equal(failure.body.message, 'This detector no longer exists.');
			return true;
		}
	);
	const defect = new Error('Unexpected implementation defect');
	await assert.rejects(
		configurationAction(Promise.reject(defect)),
		(failure) => failure === defect
	);
});

test('metadata reconciles stale labels and shared identities without mutating source documents', () => {
	const config = {
		detectors: [1, 2].map(() => ({
			detection: { source },
			exporters: { telegram: { token: 'one', chat: 'shared' } }
		}))
	};
	const app = {
		detectors: [{ label: 'Barn' }, { label: 'Barn' }, { label: 'stale' }],
		streams: [
			{ label: 'Camera', source },
			{ label: 'Camera', source }
		],
		telegrams: []
	};
	const before = structuredClone({ config, app });
	const normalized = normalizeConfiguration(config, app);
	assert.deepEqual(normalized.app.detectors, [{ label: 'Barn' }, { label: 'Barn (2)' }]);
	assert.deepEqual(normalized.app.streams, [{ label: 'Camera', source }]);
	assert.deepEqual(normalized.app.telegrams, [{ label: 'shared', token: 'one', chat: 'shared' }]);
	assert.deepEqual({ config, app }, before);
});

test('missing setup files remain distinct from malformed or null configuration', async (t) => {
	const { files, store } = await fixture(t);
	await rm(files.config);
	assert.deepEqual((await store.read()).config.detectors, []);
	for (const invalid of ['{broken', 'null']) {
		await writeFile(files.config, invalid);
		await assert.rejects(store.read());
		assert.equal(await readFile(files.config, 'utf8'), invalid);
	}
});

test('deleting or editing a stale detector never removes or overwrites the last one', async (t) => {
	const { files, store } = await fixture(t);
	const before = await readFile(files.config, 'utf8');
	await assert.rejects(store.deleteDetector('missing'), /no longer exists/);
	await assert.rejects(
		store.saveDetector({ original: 'missing', detector, meta: { label: 'Changed' } }),
		/no longer exists/
	);
	assert.equal(await readFile(files.config, 'utf8'), before);
	await store.saveDetector({ detector, meta: { label: 'Second' } });
	assert.equal((await store.read()).config.detectors.length, 2);
	await assert.rejects(
		store.saveDetector({ original: 'Second', detector, meta: { label: 'Detector 1' } }),
		/already exists/
	);
});

test('concurrent edits are serialized from read through apply and rejected writes do not poison the queue', async (t) => {
	const { files } = await fixture(t, { detectors: [] });
	let release!: () => void;
	const gate = new Promise<void>((resolve) => {
		release = resolve;
	});
	let entered!: () => void;
	const validating = new Promise<void>((resolve) => {
		entered = resolve;
	});
	const applied: number[] = [];
	const runtime = {
		async validate() {
			entered();
			await gate;
		},
		async apply() {
			applied.push(JSON.parse(await readFile(files.config, 'utf8')).detectors.length);
		},
		async stop() {},
		fail(error: unknown) {
			throw error;
		}
	};
	const store = new ConfigurationStore(files, () => runtime);
	const first = store.saveDetector({ detector, meta: { label: 'First' } });
	await validating;
	const second = store.saveDetector({
		detector: { detection: { source: [other] } },
		meta: { label: 'Second' }
	});
	release();
	await Promise.all([first, second]);
	assert.deepEqual(applied, [1, 2]);
	assert.deepEqual((await store.read()).app.detectors, [{ label: 'First' }, { label: 'Second' }]);
	await assert.rejects(
		store.saveDetector({ detector: { detection: { source: [] } }, meta: { label: 'Invalid' } }),
		ConfigurationError
	);
	await store.deleteDetector('First');
	assert.deepEqual((await store.read()).app.detectors, [{ label: 'Second' }]);
});

test('runtime validation happens before writing either configuration file', async (t) => {
	const { files } = await fixture(t);
	const before = await Promise.all([readFile(files.config, 'utf8'), readFile(files.app, 'utf8')]);
	const store = new ConfigurationStore(files, () => ({
		async validate() {
			throw new Error('Model is unavailable');
		},
		async apply() {
			assert.fail('Invalid configuration cannot be applied');
		},
		async stop() {
			assert.fail('Existing detection must not stop');
		},
		fail(error: unknown) {
			throw error;
		}
	}));
	await assert.rejects(
		store.saveDetector({
			original: 'Detector 1',
			detector: { detection: { source: other } },
			meta: { label: 'Renamed' }
		}),
		/Model is unavailable/
	);
	assert.deepEqual(
		await Promise.all([readFile(files.config, 'utf8'), readFile(files.app, 'utf8')]),
		before
	);
});

test('a configuration staging failure leaves both settings files unchanged', async (t) => {
	const { files, store } = await fixture(t, { detectors: [] });
	const before = await Promise.all([readFile(files.app), readFile(files.config)]);
	const failure = Object.assign(new Error('Configuration directory is not writable'), {
		code: 'EACCES'
	});
	const write = fs.writeFile;
	t.mock.method(fs, 'writeFile', async (...args: Parameters<typeof fs.writeFile>) => {
		if (String(args[0]).startsWith(files.config)) throw failure;
		return write(...args);
	});
	await assert.rejects(
		addPresetDetector(store, { source, label: 'Barn' }, 'general'),
		(error) => error === failure
	);
	assert.deepEqual(await Promise.all([readFile(files.app), readFile(files.config)]), before);
	assert.deepEqual((await readdir(path.dirname(files.app))).sort(), [
		'app.json',
		'config.json',
		'config.json.last-valid'
	]);
});

for (const existingApp of [true, false]) {
	test(`failed second file replacement restores ${existingApp ? 'exact previous metadata' : 'missing metadata'} and permits retry`, async (t) => {
		const { files } = await fixture(t, { detectors: [] });
		if (existingApp) await writeFile(files.app, '{ "streams": [] }');
		else await rm(files.app);
		const previousApp = existingApp ? await readFile(files.app) : null;
		const previousConfig = await readFile(files.config);
		let applied = 0;
		const store = new ConfigurationStore(files, () => ({
			async validate() {},
			async apply() {
				applied++;
			},
			async stop() {
				assert.fail('Failed save must not stop monitoring');
			},
			fail(error) {
				throw error;
			}
		}));
		const failure = Object.assign(new Error('Configuration replacement failed'), { code: 'EIO' });
		const rename = fs.rename;
		const replacement = t.mock.method(
			fs,
			'rename',
			async (from: Parameters<typeof fs.rename>[0], to: Parameters<typeof fs.rename>[1]) => {
				if (to === files.config) throw failure;
				return rename(from, to);
			}
		);
		await assert.rejects(
			addPresetDetector(store, { source, label: 'Barn' }, 'general'),
			(error) => error === failure
		);
		assert.equal(applied, 0);
		assert.deepEqual(await readFile(files.config), previousConfig);
		if (existingApp) assert.deepEqual(await readFile(files.app), previousApp);
		else await assert.rejects(readFile(files.app), { code: 'ENOENT' });
		assert.deepEqual(
			(await readdir(path.dirname(files.app))).sort(),
			existingApp
				? ['app.json', 'config.json', 'config.json.last-valid']
				: ['config.json', 'config.json.last-valid']
		);
		replacement.mock.restore();
		await addPresetDetector(store, { source, label: 'Barn' }, 'general');
		assert.equal(applied, 1);
		const saved = await store.read();
		assert.equal(saved.app.streams.length, 1);
		assert.equal(saved.config.detectors.length, 1);
	});
}

test('a rollback failure is explicit and retains the previous metadata for recovery', async (t) => {
	const { files, store } = await fixture(t, { detectors: [] });
	const previousApp = await readFile(files.app);
	const previousConfig = await readFile(files.config);
	const commitFailure = new Error('Cannot replace configuration');
	const rollbackFailure = new Error('Cannot restore metadata');
	const rename = fs.rename;
	let appReplacements = 0;
	t.mock.method(
		fs,
		'rename',
		async (from: Parameters<typeof fs.rename>[0], to: Parameters<typeof fs.rename>[1]) => {
			if (to === files.config) throw commitFailure;
			if (to === files.app && ++appReplacements === 2) throw rollbackFailure;
			return rename(from, to);
		}
	);
	await assert.rejects(addPresetDetector(store, { source, label: 'Barn' }, 'general'), (error) => {
		assert.ok(error instanceof AggregateError);
		assert.deepEqual(error.errors, [commitFailure, rollbackFailure]);
		assert.equal(error.cause, commitFailure);
		assert.match(error.message, /Recovery is required/);
		return true;
	});
	assert.deepEqual(await readFile(files.config), previousConfig);
	const backups = (await readdir(path.dirname(files.app))).filter((file) =>
		file.endsWith('.previous')
	);
	assert.equal(backups.length, 1);
	assert.deepEqual(await readFile(path.join(path.dirname(files.app), backups[0])), previousApp);
	assert.ok((await readdir(path.dirname(files.app))).every((file) => !file.endsWith('.next')));
});

test('cleanup failure is logged without misreporting a committed save as failed', async (t) => {
	const { files, store } = await fixture(t, { detectors: [] });
	const failure = new Error('Cannot remove backup');
	const remove = fs.rm;
	t.mock.method(fs, 'rm', async (...args: Parameters<typeof fs.rm>) => {
		if (String(args[0]).endsWith('.previous')) throw failure;
		return remove(...args);
	});
	const logged = t.mock.method(console, 'error', () => {});
	const camera = await addPresetDetector(store, { source, label: 'Barn' }, 'general');
	const saved = await store.read();
	assert.equal(saved.app.streams[0].id, camera.id);
	assert.equal(saved.config.detectors.length, 1);
	assert.equal(logged.mock.callCount(), 1);
	assert.match(logged.mock.calls[0].arguments[0], /Could not remove temporary settings file/);
	assert.equal(logged.mock.calls[0].arguments[1], failure);
	assert.equal(
		(await readdir(path.dirname(files.app))).filter((file) => file.endsWith('.previous')).length,
		1
	);
});

test('a committed detector save succeeds while an apply failure is reported to runtime status', async (t) => {
	const { files } = await fixture(t, { detectors: [] });
	const failure = new Error('Detector could not restart');
	const reported: unknown[] = [];
	const store = new ConfigurationStore(files, () => ({
		async validate() {},
		async apply() {
			throw failure;
		},
		async stop() {
			assert.fail('A monitored camera does not stop monitoring');
		},
		fail(error) {
			reported.push(error);
		}
	}));
	const camera = await addPresetDetector(store, { source, label: 'Barn' }, 'general');
	assert.deepEqual(reported, [failure]);
	const saved = await store.read();
	assert.equal(saved.app.streams[0].id, camera.id);
	assert.deepEqual(saved.config.detectors[0].detection.source, [source]);
	assert.equal(saved.app.streams.length, 1);
	await store.saveCamera({ id: camera.id, source, label: 'Renamed barn', mode: 'keep' });
	assert.deepEqual(reported, [failure]);
	assert.equal((await store.read()).app.streams[0].label, 'Renamed barn');
});

test('failed managed stop settings remain visible without rejecting the saved empty setup', async (t) => {
	const { files } = await fixture(t);
	// The launcher keeps its resume flag in its own app.json. An occupied path there reproduces
	// an actual filesystem rejection in stop(), without launching a child process or depending on
	// platform-specific permission behavior.
	const launcherData = await mkdtemp(path.join(tmpdir(), 'detector-launcher-'));
	t.after(() => rm(launcherData, { recursive: true, force: true }));
	await mkdir(path.join(launcherData, 'app.json'));
	const runtime = new ManagedDetector({ executable: 'unused', dataDirectory: launcherData });
	const store = new ConfigurationStore(files, () => runtime);
	try {
		await store.deleteDetector('Detector 1');
		assert.deepEqual((await store.read()).config.detectors, []);
		assert.deepEqual((await store.read()).app.detectors, []);
		assert.equal(runtime.status().phase, 'failed');
		assert.equal(runtime.status().readiness, 'failed');
		assert.match(runtime.status().message, /EISDIR|directory/);
	} finally {
		// Drain logging without rewriting the deliberately blocked settings path.
		await runtime.stop(false);
	}
});

test('metadata-only edits persist without rewriting config or restarting detection', async (t) => {
	const telegram = { token: 'token', chat: 'chat' };
	const { files } = await fixture(t, {
		detectors: [{ detection: { source }, exporters: { telegram } }]
	});
	const before = await readFile(files.config, 'utf8');
	const calls: string[] = [];
	const store = new ConfigurationStore(files, () => ({
		async validate() {
			calls.push('validate');
		},
		async apply() {
			calls.push('apply');
		},
		async stop() {
			calls.push('stop');
		},
		fail(error: unknown) {
			throw error;
		}
	}));
	const camera = (await store.read()).app.streams[0];
	await store.saveCamera({ source: other, label: 'Unused camera', mode: 'view-only' });
	await store.saveCamera({ id: camera.id, source, label: 'Renamed camera', mode: 'keep' });
	await store.saveTelegram({ label: 'Unused channel', token: 'other', chat: 'other' });
	await store.saveTelegram({ original: 'chat', label: 'Renamed channel', ...telegram });
	const { config } = await store.read();
	await store.saveDetector({
		original: 'Detector 1',
		detector: config.detectors[0],
		meta: { label: 'Renamed detector' }
	});
	await store.replace(await store.read());
	assert.deepEqual(calls, []);
	assert.equal(await readFile(files.config, 'utf8'), before);
	const saved = JSON.parse(await readFile(files.app, 'utf8'));
	assert.deepEqual(saved.detectors, [{ label: 'Renamed detector' }]);
	assert.deepEqual(
		saved.streams.map(({ label, source }: StreamMeta) => ({ label, source })),
		[
			{ label: 'Renamed camera', source },
			{ label: 'Unused camera', source: other }
		]
	);
	assert.equal(saved.telegrams.length, 2);
	const replacement = 'rtsp://camera.local/replacement';
	await store.saveCamera({
		id: camera.id,
		source: replacement,
		label: 'Renamed camera',
		mode: 'keep'
	});
	await store.saveTelegram({
		original: 'Renamed channel',
		label: 'Renamed channel',
		token: 'new',
		chat: 'chat'
	});
	assert.deepEqual(calls, ['validate', 'apply', 'validate', 'apply']);
	const updated = (await store.read()).config.detectors[0];
	assert.deepEqual(updated.detection.source, [replacement]);
	assert.equal(updated.exporters?.telegram?.[0].token, 'new');
});

test('advanced detection changes invalidate an inherited preset without losing camera identity', async (t) => {
	const changes: { name: string; change: (detector: DetectorConfig) => void }[] = [
		{
			name: 'different model',
			change: (detector) => {
				detector.yolo = { model: 'yolo11n.pt' };
			}
		},
		{
			name: 'snapshot only',
			change: (detector) => {
				detector.yolo = null;
			}
		},
		{
			name: 'different watched classes',
			change: (detector) => {
				detector.yolo!.confidence = { person: 0.7 };
			}
		},
		{
			name: 'different sampling interval',
			change: (detector) => {
				detector.detection.interval = 7;
			}
		}
	];
	for (const { name, change } of changes) {
		await t.test(name, async (t) => {
			const { store } = await fixture(t, { detectors: [] });
			const camera = await addPresetDetector(store, { label: 'Barn', source }, 'calving-catcher');
			const original = await store.read();
			const changed = structuredClone(original.config.detectors[0]);
			change(changed);
			await store.saveDetector({
				original: 'Barn',
				detector: changed,
				meta: { label: 'Updated monitoring' }
			});
			const saved = await store.read();
			assert.deepEqual(saved.app.detectors[0], {
				label: 'Updated monitoring'
			});
			assert.deepEqual(saved.config.detectors[0], changed);
			assert.equal(saved.app.streams[0].id, camera.id);
		});
	}
});

test('renaming or changing delivery settings keeps the monitoring preset and camera identity', async (t) => {
	const { store } = await fixture(t, { detectors: [] });
	const camera = await addPresetDetector(store, { label: 'Barn', source }, 'calving-catcher');
	const original = (await store.read()).config.detectors[0];
	await store.saveDetector({
		original: 'Barn',
		detector: original,
		meta: { label: 'Calving pen' }
	});
	const meta = { label: 'Calving pen', preset: 'calving-catcher' };
	assert.equal((await store.read()).app.streams[0].id, camera.id);
	assert.deepEqual((await store.read()).app.detectors[0], meta);
	const changed = structuredClone(original);
	changed.exporters = {
		disk: [{ directory: 'calving-recordings', strategy: 'ALL' }],
		telegram: [{ token: 'new-token', chat: 'new-chat', alert_every: 2 }]
	};
	await store.saveDetector({
		original: 'Calving pen',
		detector: changed,
		meta: { label: 'Calving pen' }
	});
	const saved = await store.read();
	assert.deepEqual(saved.app.detectors[0], meta);
	assert.deepEqual(saved.config.detectors[0], changed);
});

test('metadata-only first save still creates the missing empty configuration', async (t) => {
	const { files, store } = await fixture(t);
	await rm(files.config);
	await store.saveCamera({ source, label: 'First camera', mode: 'view-only' });
	assert.deepEqual(JSON.parse(await readFile(files.config, 'utf8')), {
		$schema: DEFAULT_SCHEMA_URL,
		detectors: []
	});
	assert.deepEqual(
		(await store.read()).app.streams.map(({ label, source }) => ({ label, source })),
		[{ label: 'First camera', source }]
	);
});

test('preset identity survives camera changes and follows an explicitly selected replacement', async (t) => {
	const { store } = await fixture(t, { detectors: [] });
	const presets = await readTestPresets();
	const general = structuredClone(presets.find((item) => item.id === 'general')!.detector);
	general.detection.source = [source];
	await store.saveDetector({ detector: general, meta: { label: 'Entrance', preset: 'general' } });
	const changed = (await store.read()).config.detectors[0];
	changed.detection.source = [source, other];
	await store.saveDetector({
		original: 'Entrance',
		detector: changed,
		meta: { label: 'Entrances' }
	});
	assert.equal((await store.read()).app.detectors[0].preset, 'general');
	const calving = structuredClone(presets.find((item) => item.id === 'calving-catcher')!.detector);
	calving.detection.source = [source, other];
	await store.saveDetector({
		original: 'Entrances',
		detector: calving,
		meta: { label: 'Entrances', preset: 'calving-catcher' }
	});
	assert.equal((await store.read()).app.detectors[0].preset, 'calving-catcher');
});

test('deleting the last detector saves the empty setup and stops managed detection', async (t) => {
	const { files } = await fixture(t);
	let stopped = 0;
	const store = new ConfigurationStore(files, () => ({
		async validate() {
			assert.fail('Empty setup is not executable configuration');
		},
		async apply() {
			assert.fail('Empty setup cannot start');
		},
		async stop() {
			stopped++;
		},
		fail(error: unknown) {
			throw error;
		}
	}));
	await store.deleteDetector('Detector 1');
	assert.equal(stopped, 1);
	assert.deepEqual((await store.read()).app.detectors, []);
	assert.deepEqual(JSON.parse(await readFile(files.config, 'utf8')).detectors, []);
});

test('Telegram credential edits propagate to all exporters while preserving delivery options', async (t) => {
	const original = { token: 'old-token', chat: '-10', include_video: false, alert_every: 3 };
	const { store } = await fixture(t, {
		detectors: [1, 2].map(() => ({ ...detector, exporters: { telegram: [original] } }))
	});
	await store.saveTelegram({
		original: '-10',
		label: 'Farm alerts',
		token: 'new-token',
		chat: '-20'
	});
	const changed = await store.read();
	assert.deepEqual(changed.app.telegrams, [
		{ label: 'Farm alerts', token: 'new-token', chat: '-20' }
	]);
	for (const item of changed.config.detectors) {
		assert.deepEqual(item.exporters?.telegram, [{ ...original, token: 'new-token', chat: '-20' }]);
	}
	await store.deleteTelegram('Farm alerts');
	assert.deepEqual((await store.read()).app.telegrams, []);
	assert.ok(
		(await store.read()).config.detectors.every((item) => item.exporters?.telegram?.length === 0)
	);
});

test('duplicate and stale notification edits fail without creating extra channels', async (t) => {
	const { store } = await fixture(t);
	await store.saveTelegram({ label: 'First', token: 'token', chat: 'chat' });
	await assert.rejects(
		store.saveTelegram({ label: 'Other', token: 'token', chat: 'chat' }),
		/already exists/
	);
	await assert.rejects(
		store.saveTelegram({ label: 'First', token: 'other', chat: 'other' }),
		/already exists/
	);
	await assert.rejects(
		store.saveTelegram({ original: 'missing', label: 'New', token: 'new', chat: 'new' }),
		/no longer exists/
	);
	assert.equal((await store.read()).app.telegrams.length, 1);
});

test('a changed camera address reaches every detector that uses it, and duplicates are refused', async (t) => {
	const { store } = await fixture(t, {
		detectors: [detector, { detection: { source: [source, other] } }]
	});
	const [camera, second] = (await store.read()).app.streams;
	const replacement = 'rtsp://camera.local/new';
	await store.saveCamera({
		id: camera.id,
		source: replacement,
		label: 'Renamed camera',
		mode: 'keep'
	});
	assert.deepEqual(
		(await store.read()).config.detectors.map((item) => item.detection.source),
		[[replacement], [replacement, other]]
	);
	await assert.rejects(
		store.saveCamera({ id: camera.id, source: other, label: 'Duplicate', mode: 'keep' }),
		/already saved/
	);
	await assert.rejects(
		store.saveCamera({ id: second.id, source: other, label: 'Renamed camera', mode: 'keep' }),
		/name already exists/
	);
	assert.deepEqual(
		(await store.read()).config.detectors.map((item) => item.detection.source),
		[[replacement], [replacement, other]]
	);
});

test('concurrent detector additions each save their rules and preserve notification channels', async (t) => {
	const { store } = await fixture(
		t,
		{ detectors: [], onnx: { provider: 'CPUExecutionProvider' } },
		{
			streams: [],
			telegrams: [{ label: 'Alerts', token: 'token', chat: 'chat' }]
		}
	);
	const preset = (await readTestPresets()).find(({ id }) => id === 'general')!;
	const results = await Promise.allSettled(
		[
			{ label: 'Barn', source },
			{ label: 'Second', source: other }
		].map((camera) =>
			store.saveDetector({
				detector: {
					...structuredClone(preset.detector),
					detection: { ...preset.detector.detection, source: [camera.source] }
				},
				meta: { label: camera.label, preset: preset.id }
			})
		)
	);
	assert.deepEqual(
		results.map((item) => item.status),
		['fulfilled', 'fulfilled']
	);
	const document = await store.read();
	assert.deepEqual(
		document.app.detectors.map((detector) => detector.label),
		['Barn', 'Second']
	);
	assert.deepEqual(
		document.config.detectors.map((detector) => detector.detection.source),
		[[source], [other]]
	);
	assert.equal(document.app.streams.length, 2);
	assert.equal(document.app.telegrams.length, 1);
	assert.deepEqual(document.config.onnx, { provider: 'CPUExecutionProvider' });
});

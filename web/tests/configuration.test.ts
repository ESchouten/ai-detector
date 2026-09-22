import assert from 'node:assert/strict';
import { test, type TestContext } from 'node:test';
import fs, { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { ConfigurationStore } from '../src/lib/server/configuration/store.ts';
import { ManagedDetector } from '../src/lib/server/managed-detector.ts';
import {
	normalizeConfiguration,
	ConfigurationError,
	configurationSchema
} from '../src/lib/configuration.ts';
import { DEFAULT_SCHEMA_URL, type DetectorConfig, type StreamMeta } from '../src/lib/schema.ts';
import { getEditorSchema } from '../src/lib/server/configuration/presets.ts';
import { writeJson } from '../src/lib/server/json-file.ts';
import { configurationAction } from '../src/lib/server/configuration/request.ts';
import { isHttpError } from '@sveltejs/kit';

const source = 'rtsp://camera.local/first';
const other = 'rtsp://camera.local/second';
const detector = { detection: { source: [source] } };

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

test('default editor schema works offline and custom schemas preserve editor extensions', async (t) => {
	const custom = { $defs: { DetectorConfig: { title: 'Custom editor' } }, 'x-editor': true };
	const request = t.mock.method(globalThis, 'fetch', async () => Response.json(custom));
	for (const schemaUrl of [undefined, null, DEFAULT_SCHEMA_URL])
		assert.equal(await getEditorSchema(schemaUrl), configurationSchema);
	assert.equal(request.mock.callCount(), 0);
	assert.deepEqual(await getEditorSchema('https://schema.example/custom.json'), custom);
	assert.equal(request.mock.callCount(), 1);
	assert.ok(request.mock.calls[0].arguments[1]?.signal instanceof AbortSignal);
});

test('unavailable or invalid custom editor schemas fall back to the bundled schema', async (t) => {
	const request = t.mock.method(
		globalThis,
		'fetch',
		async () => new Response(null, { status: 404 })
	);
	const url = 'https://schema.example/custom.json';
	assert.equal(await getEditorSchema(url), configurationSchema);
	request.mock.mockImplementation(async () => Response.json({ $defs: {} }));
	assert.equal(await getEditorSchema(url), configurationSchema);
	request.mock.mockImplementation(async () => {
		throw new Error('Offline');
	});
	assert.equal(await getEditorSchema(url), configurationSchema);
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
		store.saveCamera({ source, label: 'Barn', preset: 'general' }),
		(error) => error === failure
	);
	assert.deepEqual(await Promise.all([readFile(files.app), readFile(files.config)]), before);
	assert.deepEqual((await readdir(path.dirname(files.app))).sort(), ['app.json', 'config.json']);
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
			store.saveCamera({ source, label: 'Barn', preset: 'general' }),
			(error) => error === failure
		);
		assert.equal(applied, 0);
		assert.deepEqual(await readFile(files.config), previousConfig);
		if (existingApp) assert.deepEqual(await readFile(files.app), previousApp);
		else await assert.rejects(readFile(files.app), { code: 'ENOENT' });
		assert.deepEqual(
			(await readdir(path.dirname(files.app))).sort(),
			existingApp ? ['app.json', 'config.json'] : ['config.json']
		);
		replacement.mock.restore();
		await store.saveCamera({ source, label: 'Barn', preset: 'general' });
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
	await assert.rejects(store.saveCamera({ source, label: 'Barn', preset: 'general' }), (error) => {
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
	const camera = await store.saveCamera({ source, label: 'Barn', preset: 'general' });
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

test('a committed camera save succeeds while an apply failure is reported to runtime status', async (t) => {
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
	const camera = await store.saveCamera({ source, label: 'Barn', preset: 'general' });
	assert.equal(camera.monitored, true);
	assert.deepEqual(reported, [failure]);
	const saved = await store.read();
	assert.equal(saved.app.streams[0].id, camera.id);
	assert.deepEqual(saved.config.detectors[0].detection.source, [source]);
	assert.equal(saved.app.streams.length, 1);
	await store.saveCamera({ id: camera.id, source, label: 'Renamed barn', preset: 'keep' });
	assert.deepEqual(reported, [failure]);
	assert.equal((await store.read()).app.streams[0].label, 'Renamed barn');
});

test('failed managed stop settings remain visible without rejecting the saved empty setup', async (t) => {
	const { files } = await fixture(t);
	const directory = path.dirname(files.app);
	const runtime = new ManagedDetector({ executable: 'unused', dataDirectory: directory });
	// An occupied path reproduces an actual filesystem rejection in stop(), without
	// launching a child process or depending on platform-specific permission behavior.
	await mkdir(path.join(directory, 'runtime.json'));
	const store = new ConfigurationStore(files, () => runtime);
	await store.deleteDetector('Detector 1');
	assert.deepEqual((await store.read()).config.detectors, []);
	assert.deepEqual((await store.read()).app.detectors, []);
	assert.equal(runtime.status().phase, 'failed');
	assert.equal(runtime.status().readiness, 'failed');
	assert.match(runtime.status().message, /runtime\.json/);
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
	await store.saveStream({ source: other, label: 'Unused camera' });
	await store.reorderStream(0, 1);
	await store.saveStream({ original: source, source, label: 'Renamed camera' });
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
			{ label: 'Unused camera', source: other },
			{ label: 'Renamed camera', source }
		]
	);
	assert.equal(saved.telegrams.length, 2);
	const replacement = 'rtsp://camera.local/replacement';
	await store.saveStream({ original: source, source: replacement, label: 'Renamed camera' });
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
			const camera = await store.saveCamera({ label: 'Barn', source, preset: 'calving' });
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
				label: 'Updated monitoring',
				cameraId: camera.id
			});
			assert.deepEqual(saved.config.detectors[0], changed);
		});
	}
});

test('renaming or changing delivery settings keeps the monitoring preset and camera identity', async (t) => {
	const { store } = await fixture(t, { detectors: [] });
	const camera = await store.saveCamera({ label: 'Barn', source, preset: 'calving' });
	const original = (await store.read()).config.detectors[0];
	await store.saveDetector({
		original: 'Barn',
		detector: original,
		meta: { label: 'Calving pen' }
	});
	const meta = { label: 'Calving pen', cameraId: camera.id, preset: 'calving' };
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
	await store.saveStream({ source, label: 'First camera' });
	assert.deepEqual(JSON.parse(await readFile(files.config, 'utf8')), {
		$schema: DEFAULT_SCHEMA_URL,
		detectors: []
	});
	assert.deepEqual(
		(await store.read()).app.streams.map(({ label, source }) => ({ label, source })),
		[{ label: 'First camera', source }]
	);
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

test('source edits propagate, duplicates are refused, and a detector cannot lose its only source', async (t) => {
	const { store } = await fixture(t, {
		detectors: [detector, { detection: { source: [source, other] } }]
	});
	const replacement = 'rtsp://camera.local/new';
	await store.saveStream({ original: source, source: replacement, label: 'Renamed camera' });
	assert.deepEqual(
		(await store.read()).config.detectors.map((item) => item.detection.source),
		[[replacement], [replacement, other]]
	);
	await assert.rejects(
		store.saveStream({ original: replacement, source: other, label: 'Duplicate' }),
		/already exists/
	);
	await assert.rejects(store.deleteStream(replacement), /only source/);
	await store.deleteStream(other);
	assert.deepEqual(
		(await store.read()).config.detectors.map((item) => item.detection.source),
		[[replacement], [replacement]]
	);
});

test('source reorder validates indices and reorders the latest saved list', async (t) => {
	const { store } = await fixture(t);
	await store.saveStream({ source: other, label: 'Second' });
	for (const index of [-1, 0.5, 9])
		await assert.rejects(store.reorderStream(index, 0), /camera order changed/);
	await store.reorderStream(0, 1);
	assert.deepEqual(
		(await store.read()).app.streams.map((item) => item.source),
		[other, source]
	);
});

test('concurrent camera additions each save their rules and preserve notification channels', async (t) => {
	const { store } = await fixture(
		t,
		{ detectors: [], onnx: { provider: 'CPUExecutionProvider' } },
		{
			streams: [],
			telegrams: [{ label: 'Alerts', token: 'token', chat: 'chat' }]
		}
	);
	const results = await Promise.allSettled([
		store.saveCamera({ label: 'Barn', source, preset: 'general' }),
		store.saveCamera({ label: 'Second', source: other, preset: 'general' })
	]);
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

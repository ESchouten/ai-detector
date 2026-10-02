import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { mockTimeouts, realDelay } from './support/timers.ts';
import { ManagedDetector } from '../src/lib/server/managed-detector.ts';
import { chooseRuntime, dockerArguments } from '../src/lib/server/runtime-platform.ts';
import { readJson, writeJson } from '../src/lib/server/json-file.ts';

const executable = fileURLToPath(new URL('./fixtures/detector.mjs', import.meta.url));
const posixOnly = { skip: process.platform === 'win32' };
const config = { detectors: [{ detection: { source: 'rtsp://camera.local/live' } }] };

test(
	'AI connection checks clean up credentials on success, failure and cancellation without starting monitoring',
	posixOnly,
	async (t) => {
		const directory = await mkdtemp(path.join(tmpdir(), 'detector-ai-check-'));
		const detector = new ManagedDetector({ executable, dataDirectory: directory });
		t.after(async () => {
			await detector.stop();
			await rm(directory, { recursive: true, force: true });
		});
		const connection = {
			label: 'Shared AI',
			model: ['vision', 'backup'],
			key: 'test-only',
			headers: { 'X-Key': 'test-header' }
		};
		await detector.testLlm(connection);
		assert.deepEqual(await readJson(path.join(directory, 'connection-check.json')), {
			model: connection.model,
			key: connection.key,
			headers: connection.headers,
			prompt: 'Connection test',
			strategy: 'IMAGE'
		});
		await assert.rejects(detector.testLlm({ ...connection, model: 'denied' }), /Check the API key/);
		const controller = new AbortController();
		const pending = detector.testLlm({ ...connection, model: 'hold' }, controller.signal);
		const cancelled = assert.rejects(pending, /cancelled/);
		await waitFor(async () => (await readdir(directory)).includes('check-pid.txt'));
		const pid = Number(await readFile(path.join(directory, 'check-pid.txt'), 'utf8'));
		controller.abort(new Error('cancelled'));
		await cancelled;
		assert.throws(() => process.kill(pid, 0), /ESRCH/);
		const files = await readdir(directory);
		assert.ok(!files.some((file) => file.startsWith('vlm-check-')));
		assert.ok(!files.includes('starts.txt'));
	}
);

test(
	'a model download failure stays visible until the automatic retry succeeds',
	posixOnly,
	async (t) => {
		const directory = await mkdtemp(path.join(tmpdir(), 'detector-download-failure-'));
		const detector = new ManagedDetector({ executable, dataDirectory: directory });
		t.after(async () => {
			await detector.stop();
			await rm(directory, { recursive: true, force: true });
		});
		mockTimeouts(t);
		const message =
			'The detection model could not be downloaded. Check the internet connection and try again.';
		await writeJson(path.join(directory, 'config.json'), config);
		await writeJson(path.join(directory, 'fixture-options.json'), {
			crashAfterStatus: true,
			statusEvents: [
				{ version: 1, event: 'preparation_failed', at: new Date().toISOString(), message }
			]
		});
		await detector.start('native');
		await waitFor(() => detector.status().message.includes('Restarting monitoring'));
		assert.ok(detector.status().message.startsWith(message));
		assert.equal(detector.status().readiness, 'preparing');
		await writeJson(path.join(directory, 'fixture-options.json'), {});
		t.mock.timers.tick(2000);
		await waitFor(() => detector.status().phase === 'running');
		assert.ok(!detector.status().message.includes(message));
		assert.ok((await detector.log.read()).includes(message));
		assert.equal(detector.status().readiness, 'preparing');
	}
);

async function waitFor(predicate: () => boolean | Promise<boolean>) {
	for (let i = 0; i < 200; i++) {
		if (await predicate()) return;
		await realDelay(25);
	}
	assert.fail('Expected process state was not reached');
}

for (const [mode, expected] of [
	['auto', 'native'],
	['native', 'native'],
	['docker', 'docker']
] as const) {
	test(`${mode} selects ${expected}`, () => assert.equal(chooseRuntime(mode), expected));
}

test('Docker mounts the same data, requests a GPU and runs as the Linux user without a shell', () => {
	const args = dockerArguments(
		'registry/app@sha256:123',
		'/farm data/$cash',
		'farm',
		'linux',
		'1001:1001'
	);
	assert.ok(args.includes('/farm data/$cash:/data'));
	assert.ok(args.includes('1001:1001'));
	assert.equal(args[args.indexOf('--gpus') + 1], 'all');
	assert.ok(args.includes('--control-stdin'));
	assert.ok(args.includes('--status-json'));
	assert.ok(args.includes('--live-preview'));
	assert.ok(!dockerArguments('image', 'C:\\Farm data', 'farm', 'win32').includes('--user'));
});

test(
	'start is idempotent, config apply restarts once, stop drains and disables resume',
	posixOnly,
	async (t) => {
		const directory = await mkdtemp(path.join(tmpdir(), 'detector lifecycle '));
		const detector = new ManagedDetector({ executable, dataDirectory: directory });
		t.after(async () => {
			await detector.stop();
			await rm(directory, { recursive: true, force: true });
		});
		await writeJson(path.join(directory, 'config.json'), config);
		await detector.initialize();
		await Promise.all([detector.start('native'), detector.start('native')]);
		await waitFor(async () => (await detector.log.read()).includes('camera.local'));
		assert.equal(detector.status().phase, 'running');
		await assert.rejects(
			detector.whileStopped(() => assert.fail('Cannot clear a running model cache')),
			/Pause monitoring/
		);
		assert.ok(!(await detector.log.read()).includes('secret'));
		assert.equal(await readFile(path.join(directory, 'starts.txt'), 'utf8'), 'started\n');
		await detector.apply();
		await waitFor(
			async () =>
				(await readFile(path.join(directory, 'starts.txt'), 'utf8')).split('\n').length === 3
		);
		assert.match(await detector.log.read(), /Restart requested: detector settings changed/);
		await detector.stop();
		assert.match(await detector.log.read(), /Stop requested: Monitoring disabled/);
		assert.equal(await readFile(path.join(directory, 'flushed.txt'), 'utf8'), 'flushed');
		assert.equal(detector.status().phase, 'stopped');
		assert.equal(await detector.whileStopped(async () => 'cache cleared'), 'cache cleared');
		assert.deepEqual(await readJson(path.join(directory, 'runtime.json')), {
			mode: 'native',
			enabled: false
		});
		const reopened = new ManagedDetector({ executable, dataDirectory: directory });
		await reopened.initialize();
		assert.equal(reopened.status().phase, 'stopped');
	}
);

test('closing and reopening the application resumes enabled detection', posixOnly, async (t) => {
	const directory = await mkdtemp(path.join(tmpdir(), 'detector-resume-'));
	const first = new ManagedDetector({ executable, dataDirectory: directory });
	const second = new ManagedDetector({ executable, dataDirectory: directory });
	t.after(async () => {
		await first.stop();
		await second.stop();
		await rm(directory, { recursive: true, force: true });
	});
	await writeJson(path.join(directory, 'config.json'), config);
	await first.start('native');
	await first.stop(false);
	assert.match(await first.log.read(), /Stop requested: Application shutdown/);
	await second.initialize();
	await waitFor(() => second.status().phase === 'running');
});

test(
	'a failed drain rejects stop, preserves the pause choice and permits a later restart',
	posixOnly,
	async (t) => {
		const directory = await mkdtemp(path.join(tmpdir(), 'detector-failed-stop-'));
		const detector = new ManagedDetector({ executable, dataDirectory: directory });
		t.after(async () => {
			await detector.stop();
			await rm(directory, { recursive: true, force: true });
		});
		await writeJson(path.join(directory, 'config.json'), config);
		await writeJson(path.join(directory, 'fixture-options.json'), { stopExitCode: 17 });
		await detector.start('native');
		await waitFor(async () => (await detector.log.read()).includes('camera.local'));
		await assert.rejects(detector.stop(), /stopped unexpectedly/);
		assert.equal(detector.status().phase, 'failed');
		assert.equal(
			(await readJson<{ enabled: boolean }>(path.join(directory, 'runtime.json')))?.enabled,
			false
		);
		await writeJson(path.join(directory, 'fixture-options.json'), {});
		await detector.start('native');
		await waitFor(() => detector.status().phase === 'running');
		await detector.stop();
		assert.equal(detector.status().phase, 'stopped');
	}
);

test(
	'invalid initial configuration fails visibly and a process crash schedules recovery',
	posixOnly,
	async (t) => {
		const directory = await mkdtemp(path.join(tmpdir(), 'detector-failure-'));
		const detector = new ManagedDetector({ executable, dataDirectory: directory });
		t.after(async () => {
			await detector.stop();
			await rm(directory, { recursive: true, force: true });
		});
		await writeJson(path.join(directory, 'config.json'), { detectors: [] });
		await detector.start('native');
		assert.equal(detector.status().phase, 'failed');
		assert.match(detector.status().message, /Add a detector/);
		assert.equal(await readJson(path.join(directory, 'runtime.json')), null);
		await writeJson(path.join(directory, 'config.json'), config);
		await writeJson(path.join(directory, 'fixture-options.json'), { crash: true });
		await detector.start('native');
		await waitFor(() => detector.status().message.includes('Restarting monitoring'));
		assert.match(detector.status().message, /stopped unexpectedly/);
	}
);

test(
	'Docker mode without a release image gives an actionable error without launching a container',
	posixOnly,
	async (t) => {
		const directory = await mkdtemp(path.join(tmpdir(), 'detector-docker-'));
		const detector = new ManagedDetector({ executable, dataDirectory: directory });
		t.after(async () => {
			await detector.stop();
			await rm(directory, { recursive: true, force: true });
		});
		await writeJson(path.join(directory, 'config.json'), config);
		await detector.start('docker');
		assert.equal(detector.status().phase, 'failed');
		assert.match(detector.status().message, /complete application release/);
	}
);

test(
	'cancelling startup never launches the detector or enables automatic resume',
	posixOnly,
	async (t) => {
		const directory = await mkdtemp(path.join(tmpdir(), 'detector-cancel-'));
		const detector = new ManagedDetector({ executable, dataDirectory: directory });
		t.after(async () => {
			await detector.stop();
			await rm(directory, { recursive: true, force: true });
		});
		await writeJson(path.join(directory, 'config.json'), config);
		await writeJson(path.join(directory, 'fixture-options.json'), { holdCheck: true });
		const starting = detector.start('native');
		await waitFor(() => detector.status().phase === 'checking');
		await detector.stop();
		await starting;
		assert.equal(detector.status().phase, 'stopped');
		assert.deepEqual(await readJson(path.join(directory, 'runtime.json')), {
			mode: 'auto',
			enabled: false
		});
		await assert.rejects(readFile(path.join(directory, 'starts.txt')), { code: 'ENOENT' });
	}
);

test(
	'an NVIDIA Docker GPU failure is visible and links to installation help',
	posixOnly,
	async (t) => {
		const directory = await mkdtemp(path.join(tmpdir(), 'detector-gpu-'));
		const detector = new ManagedDetector({
			executable,
			dataDirectory: directory,
			dockerImage: 'example.invalid/detector@sha256:123'
		});
		const oldPath = process.env.PATH;
		t.after(async () => {
			process.env.PATH = oldPath;
			await detector.stop();
			await rm(directory, { recursive: true, force: true });
		});
		await writeFile(path.join(directory, 'nvidia-smi'), '#!/bin/sh\necho NVIDIA\n', {
			mode: 0o755
		});
		await writeFile(
			path.join(directory, 'docker'),
			'#!/bin/sh\nif [ "$1" = "info" ]; then echo linux; else echo "CUDA driver unavailable" >&2; exit 1; fi\n',
			{ mode: 0o755 }
		);
		process.env.PATH = directory + path.delimiter + oldPath;
		await writeJson(path.join(directory, 'config.json'), config);
		await detector.start('docker');
		assert.equal(detector.status().selected, 'docker');
		assert.equal(detector.status().phase, 'failed');
		assert.match(detector.status().message, /GPU check/);
		assert.match(await detector.log.read(), /CUDA driver unavailable/);
		assert.match(detector.status().helpUrl!, /^https:\/\/docs.nvidia.com/);
		assert.equal(await readJson(path.join(directory, 'runtime.json')), null);
	}
);

for (const action of ['start', 'resume', 'apply'] as const) {
	test(`stop cancels a queued ${action} before it can launch or restart`, posixOnly, async (t) => {
		const directory = await mkdtemp(path.join(tmpdir(), 'detector-queued-'));
		const detector = new ManagedDetector({ executable, dataDirectory: directory });
		t.after(async () => {
			await detector.stop();
			await rm(directory, { recursive: true, force: true });
		});
		await writeJson(path.join(directory, 'config.json'), config);
		if (action === 'resume')
			await writeJson(path.join(directory, 'runtime.json'), { mode: 'native', enabled: true });
		if (action === 'apply') {
			await detector.start('native');
			await waitFor(async () => (await detector.log.read()).includes('camera.local'));
		}
		const pending =
			action === 'start'
				? detector.start('native')
				: action === 'resume'
					? detector.initialize()
					: detector.apply();
		await detector.stop();
		await pending;
		assert.equal(detector.status().phase, 'stopped');
		assert.equal(
			(await readJson<{ enabled: boolean }>(path.join(directory, 'runtime.json')))!.enabled,
			false
		);
		if (action === 'apply')
			assert.equal(await readFile(path.join(directory, 'starts.txt'), 'utf8'), 'started\n');
		else await assert.rejects(readFile(path.join(directory, 'starts.txt')), { code: 'ENOENT' });
	});
}

test('an aborted hardware probe cannot select a fallback runtime', async () => {
	const { checkDocker } = await import('../src/lib/server/runtime-platform.ts');
	const signal = AbortSignal.abort(new Error('startup cancelled'));
	await assert.rejects(checkDocker(process.platform, signal), /startup cancelled/);
});

test(
	'cancelled validation reaps its child and removes the temporary configuration',
	posixOnly,
	async (t) => {
		const directory = await mkdtemp(path.join(tmpdir(), 'detector-validation-'));
		const detector = new ManagedDetector({ executable, dataDirectory: directory });
		const abort = new AbortController();
		await writeJson(path.join(directory, 'fixture-options.json'), { holdCheck: true });
		const validation = detector.validate(config, abort.signal);
		// Observe rejection immediately so cancellation never creates an unhandled promise.
		const cancelled = assert.rejects(validation, { name: 'AbortError' });
		t.after(async () => {
			abort.abort();
			await cancelled;
			await detector.stop();
			await rm(directory, { recursive: true, force: true });
		});
		await waitFor(async () => (await detector.log.read()).includes('Checking configuration'));
		const pid = Number(await readFile(path.join(directory, 'check-pid.txt'), 'utf8'));
		abort.abort();
		await cancelled;
		assert.throws(() => process.kill(pid, 0), { code: 'ESRCH' });
		assert.deepEqual(
			(await readdir(directory)).filter((name) => name.endsWith('.json')),
			['fixture-options.json']
		);
	}
);

test('automatic detection never invokes NVIDIA or Docker prerequisites', posixOnly, async (t) => {
	const directory = await mkdtemp(path.join(tmpdir(), 'detector-native-auto-'));
	const detector = new ManagedDetector({ executable, dataDirectory: directory });
	const oldPath = process.env.PATH;
	t.after(async () => {
		process.env.PATH = oldPath;
		await detector.stop();
		await rm(directory, { recursive: true, force: true });
	});
	for (const tool of ['nvidia-smi', 'docker'])
		await writeFile(path.join(directory, tool), '#!/bin/sh\necho invoked >> probes.txt\nexit 1\n', {
			mode: 0o755
		});
	process.env.PATH = directory + path.delimiter + oldPath;
	await writeJson(path.join(directory, 'config.json'), config);
	await detector.start('auto');
	await waitFor(() => detector.status().phase === 'running');
	assert.equal(detector.status().selected, 'native');
	assert.equal(detector.status().readiness, 'preparing');
	await assert.rejects(readFile(path.join(directory, 'probes.txt')), { code: 'ENOENT' });
});

test(
	'split structured records establish readiness while process spawn and human logs do not',
	posixOnly,
	async (t) => {
		const directory = await mkdtemp(path.join(tmpdir(), 'detector-status-protocol-'));
		const detector = new ManagedDetector({ executable, dataDirectory: directory });
		t.after(async () => {
			await detector.stop();
			await rm(directory, { recursive: true, force: true });
		});
		const source = config.detectors[0].detection.source;
		const sourceKey = createHash('sha256').update(source).digest('hex');
		await writeJson(path.join(directory, 'app.json'), {
			streams: [{ id: 'barn-camera', source, label: 'Barn' }]
		});
		await writeJson(path.join(directory, 'config.json'), config);
		await writeJson(path.join(directory, 'fixture-options.json'), {
			statusEvents: ['ready', 'frame', 'inference'].map((event) => ({
				version: 1,
				event,
				ruleId: 'detector-1',
				sourceKey,
				at: new Date().toISOString()
			}))
		});
		await detector.start('auto');
		await waitFor(() => detector.status().readiness === 'monitoring');
		assert.equal(detector.status().cameras[0].id, 'barn-camera');
		assert.ok(detector.status().cameras[0].lastInferenceAt);
		assert.ok(!(await detector.log.read()).includes('AIDETECTOR_STATUS'));
		await writeJson(path.join(directory, 'app.json'), {
			streams: [{ id: 'barn-camera', source, label: 'North barn' }]
		});
		await detector.refreshMetadata();
		assert.equal(detector.status().cameras[0].label, 'North barn');
		assert.equal(detector.status().readiness, 'monitoring');
		assert.equal(await readFile(path.join(directory, 'starts.txt'), 'utf8'), 'started\n');
		await detector.stop();
		assert.equal(detector.status().readiness, 'idle');
		assert.equal(detector.status().cameras[0].state, 'paused');
		await writeJson(path.join(directory, 'fixture-options.json'), { holdCheck: true });
		const restarting = detector.start('auto');
		await waitFor(() => detector.status().phase === 'checking');
		assert.equal(detector.status().readiness, 'preparing');
		assert.deepEqual(detector.status().cameras, []);
		await detector.stop();
		await restarting;
	}
);

test(
	'a live detector that stops processing fresh frames is drained and restarted; pause cancels supervision',
	posixOnly,
	async (t) => {
		const directory = await mkdtemp(path.join(tmpdir(), 'detector-stall-'));
		const detector = new ManagedDetector({ executable, dataDirectory: directory });
		t.after(async () => {
			await detector.stop();
			await rm(directory, { recursive: true, force: true });
		});
		const now = Date.now();
		t.mock.timers.enable({ apis: ['setInterval', 'Date'], now });
		const sourceKey = createHash('sha256')
			.update(config.detectors[0].detection.source)
			.digest('hex');
		await writeJson(path.join(directory, 'config.json'), config);
		await writeJson(path.join(directory, 'fixture-options.json'), {
			statusEvents: [
				{ version: 1, event: 'ready', at: new Date(now).toISOString() },
				{ version: 1, event: 'frame', sourceKey, at: new Date(now - 180000).toISOString() },
				{ version: 1, event: 'frame', sourceKey, at: new Date(now).toISOString() }
			]
		});
		await detector.start('native');
		await waitFor(
			() => detector.status().cameras?.[0]?.lastFrameAt === new Date(now).toISOString()
		);
		await writeJson(path.join(directory, 'fixture-options.json'), {});
		t.mock.timers.tick(5000);
		await waitFor(
			async () =>
				(await readFile(path.join(directory, 'starts.txt'), 'utf8')) === 'started\nstarted\n'
		);
		assert.match(
			await detector.log.read(),
			/Restart requested: Detector 1 stopped processing fresh camera frames/
		);
		assert.equal(await readFile(path.join(directory, 'flushed.txt'), 'utf8'), 'flushed');
		await detector.stop();
		t.mock.timers.tick(600000);
		assert.equal(detector.status().phase, 'stopped');
		assert.equal(await readFile(path.join(directory, 'starts.txt'), 'utf8'), 'started\nstarted\n');
	}
);

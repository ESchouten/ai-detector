import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtemp, readFile, readdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { executable, managedDetector } from './support/detector.ts';
import { mockTimeouts, realDelay, waitFor } from './support/timers.ts';
import { ManagedDetector } from '../src/lib/server/managed-detector.ts';
import { monitoringEnabled } from '../src/lib/server/monitoring-flag.ts';
import { readJson, writeJson } from '../src/lib/server/json-file.ts';

const posixOnly = { skip: process.platform === 'win32' };
const config = { detectors: [{ detection: { source: 'rtsp://camera.local/live' } }] };

test(
	'AI connection checks clean up credentials on success, failure and cancellation without starting monitoring',
	posixOnly,
	async (t) => {
		const { detector, directory } = await managedDetector(t);
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
		const { detector, directory } = await managedDetector(t);
		mockTimeouts(t);
		const message =
			'The detection model could not be downloaded. Check the internet connection and try again.';
		await writeJson(path.join(directory, 'config.json'), config);
		await writeJson(path.join(directory, 'fixture-options.json'), {
			crash: true,
			statusEvents: [
				{ version: 1, event: 'preparation_failed', at: new Date().toISOString(), message }
			]
		});
		await detector.start();
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

test(
	'start is idempotent, config apply restarts once, stop drains and disables resume',
	posixOnly,
	async (t) => {
		const { detector, directory } = await managedDetector(t);
		await writeJson(path.join(directory, 'config.json'), config);
		await detector.initialize();
		assert.equal(detector.monitoring, false);
		await Promise.all([detector.start(), detector.start()]);
		await waitFor(async () => (await detector.log.read()).includes('camera.local'));
		assert.equal(detector.status().phase, 'running');
		assert.equal(detector.monitoring, true);
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
		assert.equal(await monitoringEnabled(path.join(directory, 'app.json')), false);
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
	await first.start();
	await first.stop(false);
	assert.match(await first.log.read(), /Stop requested: Application shutdown/);
	await second.initialize();
	await waitFor(() => second.status().phase === 'running');
});

test(
	'a failed drain rejects stop, preserves the pause choice and permits a later restart',
	posixOnly,
	async (t) => {
		const { detector, directory } = await managedDetector(t);
		await writeJson(path.join(directory, 'config.json'), config);
		await writeJson(path.join(directory, 'fixture-options.json'), { stopExitCode: 17 });
		await detector.start();
		await waitFor(async () => (await detector.log.read()).includes('camera.local'));
		await assert.rejects(detector.stop(), /stopped unexpectedly/);
		assert.equal(detector.status().phase, 'failed');
		assert.doesNotMatch(await detector.log.read(), /Restarting the detector/);
		assert.equal(await readFile(path.join(directory, 'starts.txt'), 'utf8'), 'started\n');
		assert.equal(await monitoringEnabled(path.join(directory, 'app.json')), false);
		await writeJson(path.join(directory, 'fixture-options.json'), {});
		await detector.start();
		await waitFor(() => detector.status().phase === 'running');
		await detector.stop();
		assert.equal(detector.status().phase, 'stopped');
	}
);

test(
	'invalid initial configuration fails visibly and a process crash schedules recovery',
	posixOnly,
	async (t) => {
		const { detector, directory } = await managedDetector(t);
		await writeJson(path.join(directory, 'config.json'), { detectors: [] });
		await detector.start();
		assert.equal(detector.status().phase, 'failed');
		assert.match(detector.status().message, /Add a detector/);
		assert.equal(await monitoringEnabled(path.join(directory, 'app.json')), false);
		await writeJson(path.join(directory, 'config.json'), config);
		await writeJson(path.join(directory, 'fixture-options.json'), { crash: true });
		await detector.start();
		await waitFor(() => detector.status().message.includes('Restarting monitoring'));
		assert.match(detector.status().message, /stopped unexpectedly/);
	}
);

test(
	'cancelling startup never launches the detector or enables automatic resume',
	posixOnly,
	async (t) => {
		const { detector, directory } = await managedDetector(t);
		await writeJson(path.join(directory, 'config.json'), config);
		await writeJson(path.join(directory, 'fixture-options.json'), { holdCheck: true });
		const starting = detector.start();
		await waitFor(() => detector.status().phase === 'checking');
		// Switched on from the first moment, though nothing resumes it yet if this start fails.
		assert.equal(detector.monitoring, true);
		assert.equal(await monitoringEnabled(path.join(directory, 'app.json')), false);
		await detector.stop();
		await starting;
		assert.equal(detector.status().phase, 'stopped');
		assert.equal(detector.monitoring, false);
		assert.equal(await monitoringEnabled(path.join(directory, 'app.json')), false);
		await assert.rejects(readFile(path.join(directory, 'starts.txt')), { code: 'ENOENT' });
	}
);

for (const action of ['start', 'resume', 'apply'] as const) {
	test(`stop cancels a queued ${action} before it can launch or restart`, posixOnly, async (t) => {
		const { detector, directory } = await managedDetector(t);
		await writeJson(path.join(directory, 'config.json'), config);
		if (action === 'resume')
			await writeJson(path.join(directory, 'app.json'), { monitoring: true });
		if (action === 'apply') {
			await detector.start();
			await waitFor(async () => (await detector.log.read()).includes('camera.local'));
		}
		const pending =
			action === 'start'
				? detector.start()
				: action === 'resume'
					? detector.initialize()
					: detector.apply();
		await detector.stop();
		await pending;
		assert.equal(detector.status().phase, 'stopped');
		assert.equal(await monitoringEnabled(path.join(directory, 'app.json')), false);
		if (action === 'apply')
			assert.equal(await readFile(path.join(directory, 'starts.txt'), 'utf8'), 'started\n');
		else await assert.rejects(readFile(path.join(directory, 'starts.txt')), { code: 'ENOENT' });
	});
}

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

test(
	'split structured records establish readiness while process spawn and human logs do not',
	posixOnly,
	async (t) => {
		const { detector, directory } = await managedDetector(t);
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
		await detector.start();
		await waitFor(() => detector.status().readiness === 'monitoring');
		assert.equal(detector.status().cameras[0].id, 'barn-camera');
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
		const restarting = detector.start();
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
		const { detector, directory } = await managedDetector(t);
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
		await detector.start();
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

test(
	'a detector that reports nothing for a minute is stopped by force and restarted; waking from sleep postpones it',
	posixOnly,
	async (t) => {
		const { detector, directory } = await managedDetector(t);
		t.mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: Date.now() });
		const sourceKey = createHash('sha256')
			.update(config.detectors[0].detection.source)
			.digest('hex');
		const nextStartReportsIn = (seconds: number, extra = {}) =>
			writeJson(path.join(directory, 'fixture-options.json'), {
				...extra,
				statusEvents: ['ready', 'frame', 'inference'].map((event) => ({
					version: 1,
					event,
					ruleId: 'detector-1',
					sourceKey,
					at: new Date(Date.now() + seconds * 1000).toISOString()
				}))
			});
		// The watchdog looks every five seconds; one longer tick is a pause to it.
		const watch = (seconds: number) => {
			for (let elapsed = 0; elapsed < seconds; elapsed += 5) t.mock.timers.tick(5000);
		};
		const restarts = async () => {
			await realDelay(0);
			const log = await detector.log.read();
			return (log.match(/Restart requested: the detector reported nothing for a minute/g) ?? [])
				.length;
		};
		await writeJson(path.join(directory, 'config.json'), config);
		// Ten real seconds to stop outlasts the limit on this test's clock, as a frozen detector
		// would, and still ends by itself should the test fail first.
		await nextStartReportsIn(0, { stopDelayMs: 10000 });
		await detector.start();
		await waitFor(() => detector.status().readiness === 'monitoring');
		await nextStartReportsIn(60 + 5 + 30);

		watch(60);
		assert.equal(await restarts(), 0);
		watch(5);
		await waitFor(() => detector.status().phase === 'stopping');
		assert.match(detector.status().message, /stopped responding/);
		t.mock.timers.tick(30000);
		await waitFor(() => detector.status().readiness === 'monitoring');
		const log = await detector.log.read();
		assert.match(log, /Detector exited: SIGKILL/);
		assert.doesNotMatch(log, /stopped processing fresh camera frames/);
		assert.equal(await restarts(), 1);

		// An hour asleep, then two minutes for the detector to report again.
		await nextStartReportsIn(3600 + 120);
		t.mock.timers.tick(3600000);
		watch(115);
		assert.equal(await restarts(), 1);
		watch(5);
		await waitFor(() => detector.status().readiness === 'monitoring');
		assert.equal(await restarts(), 2);
		assert.equal(
			await readFile(path.join(directory, 'starts.txt'), 'utf8'),
			'started\nstarted\nstarted\n'
		);
	}
);

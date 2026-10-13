import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { test, type TestContext } from 'node:test';
import { executable, managedDetector } from './support/detector.ts';
import { mockTimeouts, realDelay, waitFor } from './support/timers.ts';
import { monitoringSummary } from '../src/lib/monitoring.ts';
import { ManagedDetector } from '../src/lib/server/managed-detector.ts';
import { monitoringEnabled } from '../src/lib/server/monitoring-flag.ts';
import { readJson, writeJson } from '../src/lib/server/json-file.ts';

const posixOnly = { skip: process.platform === 'win32' };
const source = 'rtsp://camera.local/live';
const config = { detectors: [{ detection: { source } }] };
const keepsStopping =
	'The detector keeps stopping unexpectedly (75). Restart this computer. If it keeps happening, download the diagnostics in Settings → Logs and ask for help.';
const scope = { stale: false, configured: true };

async function fixture(t: TestContext, extra = {}) {
	const { detector, directory } = await managedDetector(t);
	mockTimeouts(t);
	const options = {
		failureExitCode: 75,
		statusEvents: ['ready', 'frame', 'inference'].map((event) => ({
			version: 1,
			event,
			ruleId: 'detector-1',
			sourceKey: createHash('sha256').update(source).digest('hex'),
			at: new Date().toISOString()
		})),
		...extra
	};
	await writeJson(path.join(directory, 'config.json'), config);
	await writeJson(path.join(directory, 'fixture-options.json'), options);
	await detector.start();
	await waitFor(() => detector.status().readiness === 'monitoring');
	return {
		detector,
		directory,
		options,
		pid: async () => Number(await readFile(path.join(directory, 'pid.txt'), 'utf8')),
		starts: async () =>
			(await readFile(path.join(directory, 'starts.txt'), 'utf8')).trim().split('\n').length
	};
}

test(
	'completed model builds trigger one drained restart and preserve monitoring settings',
	posixOnly,
	async (t) => {
		const modelsReady = { version: 1, event: 'models_ready', at: new Date().toISOString() };
		const { detector, directory, pid, starts } = await fixture(t, {
			modelsReadyEvents: [modelsReady, modelsReady]
		});
		const originalPid = await pid();
		process.kill(originalPid, 'SIGUSR1');
		await waitFor(
			async () => (await starts()) === 2 && detector.status().readiness === 'monitoring'
		);
		assert.notEqual(await pid(), originalPid);
		assert.equal(await readFile(path.join(directory, 'flushed.txt'), 'utf8'), 'flushed');
		assert.throws(() => process.kill(originalPid, 0), { code: 'ESRCH' });
		assert.deepEqual(await readJson(path.join(directory, 'config.json')), config);
		assert.equal(await monitoringEnabled(path.join(directory, 'app.json')), true);
		const log = await detector.log.read();
		assert.equal(log.match(/Restart requested: TensorRT models are ready/g)?.length, 1);
		assert.doesNotMatch(log, /ERROR|stopped unexpectedly|Restarting the detector in/);
		await detector.stop();
		assert.equal(await starts(), 2);
	}
);

for (const disable of [true, false]) {
	test(
		`${disable ? 'pause' : 'quit'} during a model restart prevents relaunch`,
		posixOnly,
		async (t) => {
			const { detector, directory, pid, starts } = await fixture(t, { stopDelayMs: 500 });
			process.kill(await pid(), 'SIGUSR1');
			await waitFor(() => detector.status().phase === 'stopping');
			await detector.stop(disable);
			assert.equal(await starts(), 1);
			assert.equal(detector.status().phase, 'stopped');
			assert.equal(await readFile(path.join(directory, 'flushed.txt'), 'utf8'), 'flushed');
			assert.equal(await monitoringEnabled(path.join(directory, 'app.json')), !disable);
		}
	);
}

test('invalid model completion records cannot request a restart', posixOnly, async (t) => {
	const { detector, pid, starts } = await fixture(t, {
		modelsReadyEvents: [
			{ version: 2, event: 'models_ready', at: new Date().toISOString() },
			{ version: 1, event: 'models_ready', at: 'invalid' }
		]
	});
	process.kill(await pid(), 'SIGUSR1');
	await realDelay(100);
	assert.equal(await starts(), 1);
	assert.equal(detector.status().readiness, 'monitoring');
	assert.doesNotMatch(await detector.log.read(), /Restart requested/);
});

test(
	'an MPS failure starts a fresh process and retains diagnostics without stale readiness',
	posixOnly,
	async (t) => {
		const { detector, directory, pid, starts } = await fixture(t);
		const originalPid = await pid();
		process.kill(originalPid, 'SIGUSR2');
		await waitFor(() => detector.status().message.includes('Restarting monitoring'));
		assert.equal(detector.status().readiness, 'preparing');
		assert.deepEqual(detector.status().cameras, []);
		assert.match(await detector.log.read(), /Injected inference failure/);
		assert.throws(() => process.kill(originalPid, 0), { code: 'ESRCH' });

		t.mock.timers.tick(2000);
		await waitFor(() => detector.status().readiness === 'monitoring');
		assert.notEqual(await pid(), originalPid);
		assert.equal(await starts(), 2);
		assert.match(await detector.log.read(), /Injected inference failure/);
		assert.match(await detector.log.read(), /Restarting the detector/);
		assert.ok(!(await detector.log.read()).includes('secret'));
		assert.deepEqual(await readJson(path.join(directory, 'config.json')), config);
		assert.equal(await monitoringEnabled(path.join(directory, 'app.json')), true);
	}
);

test(
	'repeated crashes keep restarting with capped backoff, reset after a stable run',
	posixOnly,
	async (t) => {
		let now = Date.now();
		t.mock.method(Date, 'now', () => now);
		const { detector, directory, options, pid, starts } = await fixture(t);
		const waits = [2000, 4000, 8000, 16000, 30000, 30000, 30000];
		for (let attempt = 1; attempt <= 7; attempt++) {
			process.kill(await pid(), 'SIGUSR2');
			await waitFor(() =>
				detector
					.status()
					.message.includes(`Restarting monitoring in ${waits[attempt - 1] / 1000} seconds`)
			);
			// From the fifth stop in a row the screen says so, with what to do.
			assert.equal(detector.status().failing, attempt >= 5 ? keepsStopping : undefined);
			assert.equal(
				detector.status().message,
				`${attempt >= 5 ? keepsStopping : 'The detector stopped unexpectedly (75).'} Restarting monitoring in ${waits[attempt - 1] / 1000} seconds…`
			);
			t.mock.timers.tick(waits[attempt - 1] - 1);
			await realDelay(0);
			assert.equal(await starts(), attempt);
			t.mock.timers.tick(1);
			await waitFor(
				async () => (await starts()) === attempt + 1 && detector.status().readiness === 'monitoring'
			);
			// A detector that is ready again ends it.
			assert.equal(detector.status().failing, undefined);
		}
		now += 10 * 60 * 1000;
		await writeJson(path.join(directory, 'fixture-options.json'), {
			...options,
			statusEvents: options.statusEvents.map((event) => ({
				...event,
				at: new Date(now).toISOString()
			}))
		});
		process.kill(await pid(), 'SIGUSR2');
		await waitFor(() => detector.status().message.includes('Restarting monitoring in 2 seconds'));
		assert.equal(detector.status().failing, undefined);
		assert.match(detector.status().message, /^The detector stopped unexpectedly \(75\)\. /);
		t.mock.timers.tick(2000);
		await waitFor(
			async () => (await starts()) === 9 && detector.status().readiness === 'monitoring'
		);
	}
);

/** Lets the detector stop this many times in a row; the last stop is left waiting to restart. */
async function stopInARow(
	t: TestContext,
	{ detector, pid, starts }: Awaited<ReturnType<typeof fixture>>,
	times: number
) {
	const waits = [2000, 4000, 8000, 16000, 30000];
	for (let stop = 1; stop <= times; stop++) {
		process.kill(await pid(), 'SIGUSR2');
		await waitFor(() => detector.status().message.includes('Restarting monitoring'));
		if (stop === times) return;
		t.mock.timers.tick(waits[stop - 1]);
		await waitFor(
			async () => (await starts()) === stop + 1 && detector.status().readiness === 'monitoring'
		);
	}
}

test(
	'after five stops in a row the reason stays until a detector is ready, not until one runs',
	posixOnly,
	async (t) => {
		const running = await fixture(t);
		const { detector, directory, options, pid, starts } = running;
		await stopInARow(t, running, 5);
		// The sixth process comes up and says nothing yet: it is alive, and proves nothing.
		await writeJson(path.join(directory, 'fixture-options.json'), {
			...options,
			statusEvents: [],
			modelsReadyEvents: [{ version: 1, event: 'ready', at: new Date().toISOString() }]
		});
		t.mock.timers.tick(30000);
		await waitFor(async () => (await starts()) === 6 && detector.status().phase === 'running');
		assert.equal(detector.status().failing, keepsStopping);
		const summary = monitoringSummary(detector.status(), scope);
		assert.deepEqual(
			[summary.tone, summary.label, summary.detail, summary.attention, summary.action],
			['bad', 'Monitoring stopped', keepsStopping, true, 'pause']
		);
		process.kill(await pid(), 'SIGUSR1');
		await waitFor(() => detector.status().failing === undefined);
		assert.equal(monitoringSummary(detector.status(), scope).tone, 'busy');
	}
);

test('pausing hides the reason, and a start by hand is a start again', posixOnly, async (t) => {
	const running = await fixture(t);
	const { detector, directory, options, starts } = running;
	await stopInARow(t, running, 5);
	assert.equal(detector.status().failing, keepsStopping);
	await detector.stop();
	assert.equal(detector.status().failing, undefined);
	assert.equal(monitoringSummary(detector.status(), scope).label, 'Paused');
	// The process started by hand says nothing yet, so only the start itself can have ended it.
	await writeJson(path.join(directory, 'fixture-options.json'), { ...options, statusEvents: [] });
	await detector.start();
	await waitFor(async () => (await starts()) === 6 && detector.status().phase === 'running');
	assert.equal(detector.status().failing, undefined);
	assert.equal(monitoringSummary(detector.status(), scope).tone, 'busy');
	// Counting starts over: the next stop is a first one.
	await stopInARow(t, running, 1);
	assert.equal(detector.status().failing, undefined);
	assert.equal(
		detector.status().message,
		'The detector stopped unexpectedly (75). Restarting monitoring in 2 seconds…'
	);
});

test('a restart for new settings after a good run is not a stop in a row', posixOnly, async (t) => {
	let now = Date.now();
	t.mock.method(Date, 'now', () => now);
	const running = await fixture(t);
	const { detector, directory, options, starts } = running;
	await stopInARow(t, running, 4);
	t.mock.timers.tick(16000);
	await waitFor(async () => (await starts()) === 5 && detector.status().readiness === 'monitoring');
	// Six hours of monitoring, then settings are saved.
	now += 6 * 3600 * 1000;
	await writeJson(path.join(directory, 'fixture-options.json'), {
		...options,
		statusEvents: options.statusEvents.map((event) => ({
			...event,
			at: new Date(now).toISOString()
		}))
	});
	await detector.apply();
	await waitFor(async () => (await starts()) === 6 && detector.status().readiness === 'monitoring');
	await stopInARow(t, running, 1);
	assert.equal(detector.status().failing, undefined);
	assert.equal(
		detector.status().message,
		'The detector stopped unexpectedly (75). Restarting monitoring in 2 seconds…'
	);
});

test('a stop that explains itself is shown with its own explanation', posixOnly, async (t) => {
	const running = await fixture(t);
	const { detector, directory, starts } = running;
	const message =
		'The detection model could not be downloaded. Check the internet connection and try again.';
	await writeJson(path.join(directory, 'fixture-options.json'), {
		crash: true,
		statusEvents: [
			{ version: 1, event: 'preparation_failed', at: new Date().toISOString(), message }
		]
	});
	process.kill(await running.pid(), 'SIGUSR2');
	const waits = [2000, 4000, 8000, 16000];
	for (const [index, wait] of waits.entries()) {
		await waitFor(() =>
			detector.status().message.includes(`Restarting monitoring in ${wait / 1000} seconds`)
		);
		assert.equal(detector.status().failing, undefined);
		t.mock.timers.tick(wait);
		await waitFor(async () => (await starts()) === index + 2);
	}
	await waitFor(() => detector.status().message.includes('Restarting monitoring in 30 seconds'));
	assert.equal(detector.status().failing, message);
});

for (const disable of [true, false]) {
	test(`${disable ? 'pausing' : 'quitting'} cancels a pending recovery`, posixOnly, async (t) => {
		const { detector, directory, pid, starts } = await fixture(t);
		process.kill(await pid(), 'SIGUSR2');
		await waitFor(() => detector.status().message.includes('Restarting monitoring'));
		await detector.stop(disable);
		assert.equal(detector.status().phase, 'stopped');
		assert.equal(detector.status().readiness, 'idle');
		assert.equal(await monitoringEnabled(path.join(directory, 'app.json')), !disable);
		t.mock.timers.tick(2100);
		await realDelay(0);
		assert.equal(await starts(), 1);
	});
}

test(
	'a failed recovery stays visible and keeps retrying until settings work again',
	posixOnly,
	async (t) => {
		const { detector, directory, pid, starts } = await fixture(t);
		process.kill(await pid(), 'SIGUSR2');
		await waitFor(() => detector.status().message.includes('Restarting monitoring'));
		await writeJson(path.join(directory, 'config.json'), { detectors: [] });
		t.mock.timers.tick(2000);
		await waitFor(() => detector.status().message.includes('Add a detector'));
		assert.match(detector.status().message, /Add a detector/);
		assert.match(detector.status().message, /Restarting monitoring in 4 seconds/);
		assert.equal(detector.status().readiness, 'preparing');
		assert.match(await detector.log.read(), /Injected inference failure/);
		assert.equal(await starts(), 1);
		await writeJson(path.join(directory, 'config.json'), config);
		t.mock.timers.tick(4000);
		await waitFor(() => detector.status().readiness === 'monitoring');
		assert.equal(await starts(), 2);
	}
);

test(
	'pausing cancels validation during recovery and allows a later manual start',
	posixOnly,
	async (t) => {
		const { detector, directory, pid, starts } = await fixture(t);
		process.kill(await pid(), 'SIGUSR2');
		await waitFor(() => detector.status().message.includes('Restarting monitoring'));
		await writeJson(path.join(directory, 'fixture-options.json'), { holdCheck: true });
		t.mock.timers.tick(2000);
		await waitFor(async () => (await detector.log.read()).includes('Checking configuration'));
		const checkPid = Number(await readFile(path.join(directory, 'check-pid.txt'), 'utf8'));
		await detector.stop();
		assert.equal(detector.status().phase, 'stopped');
		assert.throws(() => process.kill(checkPid, 0), { code: 'ESRCH' });
		assert.equal(await starts(), 1);
		await writeJson(path.join(directory, 'fixture-options.json'), {});
		await detector.start();
		await waitFor(async () => (await detector.log.read()).includes('camera.local'));
		assert.equal(await starts(), 2);
	}
);

for (const exitCode of [0, 1, 2, 139]) {
	test(`unexpected exit ${exitCode} restarts monitoring`, posixOnly, async (t) => {
		const { detector, pid, starts } = await fixture(t, { failureExitCode: exitCode });
		const originalPid = await pid();
		process.kill(originalPid, 'SIGUSR2');
		await waitFor(() => detector.status().message.includes('Restarting monitoring'));
		t.mock.timers.tick(2000);
		await waitFor(
			async () => (await starts()) === 2 && detector.status().readiness === 'monitoring'
		);
		assert.notEqual(await pid(), originalPid);
		assert.match(await detector.log.read(), new RegExp(`Detector exited: ${exitCode}`));
	});
}

test('a hard process termination restarts monitoring', posixOnly, async (t) => {
	const { detector, pid, starts } = await fixture(t);
	const originalPid = await pid();
	process.kill(originalPid, 'SIGKILL');
	await waitFor(() => detector.status().message.includes('Restarting monitoring'));
	t.mock.timers.tick(2000);
	await waitFor(async () => (await starts()) === 2 && detector.status().readiness === 'monitoring');
	assert.notEqual(await pid(), originalPid);
	assert.match(await detector.log.read(), /Detector exited: SIGKILL/);
});

test(
	'an enabled installation retries a failed startup when the app reopens',
	posixOnly,
	async (t) => {
		const { detector, directory, starts } = await fixture(t);
		detector.log.append('Diagnostic from the previous application process\n');
		await detector.stop(false);
		const reopened = new ManagedDetector({ executable, dataDirectory: directory });
		try {
			await writeJson(path.join(directory, 'config.json'), { detectors: [] });
			await reopened.initialize();
			assert.match(await reopened.log.read(), /Diagnostic from the previous application process/);
			assert.match(reopened.status().message, /Add a detector.*Restarting monitoring/);
			await writeJson(path.join(directory, 'config.json'), config);
			t.mock.timers.tick(2000);
			await waitFor(() => reopened.status().readiness === 'monitoring');
			assert.equal(await starts(), 2);
		} finally {
			await reopened.stop();
		}
	}
);

test(
	'a failed drain while applying settings still resumes enabled monitoring',
	posixOnly,
	async (t) => {
		const { detector, directory, options, starts } = await fixture(t, { stopExitCode: 75 });
		await writeJson(path.join(directory, 'fixture-options.json'), { ...options, stopExitCode: 0 });
		await detector.apply();
		await waitFor(
			async () => (await starts()) === 2 && detector.status().readiness === 'monitoring'
		);
		assert.match(await detector.log.read(), /Restart requested: detector settings changed/);
	}
);

test(
	'pausing saves the disabled choice before a slow detector finishes draining',
	posixOnly,
	async (t) => {
		const { detector, directory, pid } = await fixture(t, { ignoreStop: true });
		const childPid = await pid();
		const stopped = assert.rejects(detector.stop(), /stopped unexpectedly/);
		await waitFor(async () => !(await monitoringEnabled(path.join(directory, 'app.json'))));
		process.kill(childPid, 0); // Still draining: a web crash now must not restore enabled monitoring.
		process.kill(childPid, 'SIGKILL');
		await stopped;
		const reopened = new ManagedDetector({ executable, dataDirectory: directory });
		await reopened.initialize();
		assert.equal(reopened.status().phase, 'stopped');
	}
);

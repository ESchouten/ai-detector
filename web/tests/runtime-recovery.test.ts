import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { syncBuiltinESMExports } from 'node:module';
import path from 'node:path';
import timers, { setTimeout } from 'node:timers/promises';
import { test, type TestContext } from 'node:test';
import { fileURLToPath } from 'node:url';
import { ManagedDetector } from '../src/lib/server/managed-detector.ts';
import { readJson, writeJson } from '../src/lib/server/json-file.ts';

const executable = fileURLToPath(new URL('./fixtures/detector.mjs', import.meta.url));
const posixOnly = { skip: process.platform === 'win32' };
const source = 'rtsp://camera.local/live';
const config = { detectors: [{ detection: { source } }] };

async function waitFor(predicate: () => boolean | Promise<boolean>) {
	for (let i = 0; i < 200; i++) {
		if (await predicate()) return;
		await setTimeout(25);
	}
	assert.fail('Expected recovery state was not reached');
}

async function fixture(t: TestContext, extra = {}) {
	const directory = await mkdtemp(path.join(tmpdir(), 'detector-recovery-'));
	const detector = new ManagedDetector({ executable, dataDirectory: directory });
	t.after(async () => {
		await detector.stop();
		await rm(directory, { recursive: true, force: true });
	});
	const settings = {
		...config,
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
	await writeJson(path.join(directory, 'config.json'), settings);
	await detector.start('auto');
	await waitFor(() => detector.status().readiness === 'monitoring');
	return {
		detector,
		directory,
		settings,
		pid: async () => Number(await readFile(path.join(directory, 'pid.txt'), 'utf8')),
		starts: async () =>
			(await readFile(path.join(directory, 'starts.txt'), 'utf8')).trim().split('\n').length
	};
}

test(
	'an MPS failure starts a fresh process and retains diagnostics without stale readiness',
	posixOnly,
	async (t) => {
		const { detector, directory, settings, pid, starts } = await fixture(t);
		const originalPid = await pid();
		process.kill(originalPid, 'SIGUSR2');
		await waitFor(() => detector.status().message.includes('Restarting monitoring'));
		assert.equal(detector.status().readiness, 'preparing');
		assert.deepEqual(detector.status().cameras, []);
		assert.match(await detector.log.read(), /Injected inference failure/);
		assert.throws(() => process.kill(originalPid, 0), { code: 'ESRCH' });

		await waitFor(() => detector.status().readiness === 'monitoring');
		assert.notEqual(await pid(), originalPid);
		assert.equal(await starts(), 2);
		assert.match(await detector.log.read(), /Injected inference failure/);
		assert.match(await detector.log.read(), /Restarting the detector/);
		assert.ok(!(await detector.log.read()).includes('secret'));
		assert.deepEqual(await readJson(path.join(directory, 'config.json')), settings);
		assert.deepEqual(await readJson(path.join(directory, 'runtime.json')), {
			mode: 'auto',
			enabled: true
		});
	}
);

test(
	'repeated crashes keep restarting with capped backoff, reset after a stable run',
	posixOnly,
	async (t) => {
		let now = Date.now();
		t.mock.method(Date, 'now', () => now);
		const { detector, directory, settings, pid, starts } = await fixture(t);
		const waits: number[] = [];
		const realTimeout = timers.setTimeout;
		t.mock.method(
			timers,
			'setTimeout',
			(ms: number, value?: unknown, options?: Parameters<typeof setTimeout>[2]) => {
				if (ms >= 2000) waits.push(ms);
				return realTimeout(Math.min(ms, 50), value, options);
			}
		);
		syncBuiltinESMExports();
		t.after(() => {
			t.mock.restoreAll();
			syncBuiltinESMExports();
		});
		for (let attempt = 1; attempt <= 7; attempt++) {
			process.kill(await pid(), 'SIGUSR2');
			await waitFor(
				async () => (await starts()) === attempt + 1 && detector.status().readiness === 'monitoring'
			);
		}
		now += 10 * 60 * 1000;
		await writeJson(path.join(directory, 'config.json'), {
			...settings,
			statusEvents: settings.statusEvents.map((event) => ({
				...event,
				at: new Date(now).toISOString()
			}))
		});
		process.kill(await pid(), 'SIGUSR2');
		await waitFor(
			async () => (await starts()) === 9 && detector.status().readiness === 'monitoring'
		);
		assert.deepEqual(waits, [2000, 4000, 8000, 16000, 30000, 30000, 30000, 2000]);
	}
);

for (const disable of [true, false]) {
	test(`${disable ? 'pausing' : 'quitting'} cancels a pending recovery`, posixOnly, async (t) => {
		const { detector, directory, pid, starts } = await fixture(t);
		process.kill(await pid(), 'SIGUSR2');
		await waitFor(() => detector.status().message.includes('Restarting monitoring'));
		await detector.stop(disable);
		assert.equal(detector.status().phase, 'stopped');
		assert.equal(detector.status().readiness, 'idle');
		assert.deepEqual(await readJson(path.join(directory, 'runtime.json')), {
			mode: 'auto',
			enabled: !disable
		});
		await setTimeout(2100);
		assert.equal(await starts(), 1);
	});
}

test(
	'a failed recovery stays visible and keeps retrying until settings work again',
	posixOnly,
	async (t) => {
		const { detector, directory, settings, pid, starts } = await fixture(t);
		process.kill(await pid(), 'SIGUSR2');
		await waitFor(() => detector.status().message.includes('Restarting monitoring'));
		await writeJson(path.join(directory, 'config.json'), { detectors: [] });
		await waitFor(() => detector.status().message.includes('Add a detector'));
		assert.match(detector.status().message, /Add a detector/);
		assert.match(detector.status().message, /Restarting monitoring in 4 seconds/);
		assert.equal(detector.status().readiness, 'preparing');
		assert.match(await detector.log.read(), /Injected inference failure/);
		assert.equal(await starts(), 1);
		await writeJson(path.join(directory, 'config.json'), settings);
		// The second attempt waits four seconds; allow for startup after that delay.
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
		await writeJson(path.join(directory, 'config.json'), { ...config, holdCheck: true });
		await waitFor(async () => (await detector.log.read()).includes('Checking configuration'));
		const checkPid = Number(await readFile(path.join(directory, 'check-pid.txt'), 'utf8'));
		await detector.stop();
		assert.equal(detector.status().phase, 'stopped');
		assert.throws(() => process.kill(checkPid, 0), { code: 'ESRCH' });
		assert.equal(await starts(), 1);
		await writeJson(path.join(directory, 'config.json'), config);
		await detector.start('auto');
		await waitFor(async () => (await detector.log.read()).includes('camera.local'));
		assert.equal(await starts(), 2);
	}
);

for (const exitCode of [0, 1, 2, 139]) {
	test(`unexpected exit ${exitCode} restarts monitoring`, posixOnly, async (t) => {
		const { detector, pid, starts } = await fixture(t, { failureExitCode: exitCode });
		const originalPid = await pid();
		process.kill(originalPid, 'SIGUSR2');
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
	await waitFor(async () => (await starts()) === 2 && detector.status().readiness === 'monitoring');
	assert.notEqual(await pid(), originalPid);
	assert.match(await detector.log.read(), /Detector exited: SIGKILL/);
});

test(
	'an enabled installation retries a failed startup when the app reopens',
	posixOnly,
	async (t) => {
		const { detector, directory, settings, starts } = await fixture(t);
		detector.log.append('Diagnostic from the previous application process\n');
		await detector.stop(false);
		const reopened = new ManagedDetector({ executable, dataDirectory: directory });
		try {
			await writeJson(path.join(directory, 'config.json'), { detectors: [] });
			await reopened.initialize();
			assert.match(await reopened.log.read(), /Diagnostic from the previous application process/);
			assert.match(reopened.status().message, /Add a detector.*Restarting monitoring/);
			await writeJson(path.join(directory, 'config.json'), settings);
			await waitFor(() => reopened.status().readiness === 'monitoring');
			assert.equal(await starts(), 2);
		} finally {
			await reopened.stop();
		}
	}
);

test('an MPS error while stopping never reverses the requested shutdown', posixOnly, async (t) => {
	const { detector, starts } = await fixture(t, { stopExitCode: 75 });
	await assert.rejects(detector.stop(), /stopped unexpectedly/);
	assert.equal(detector.status().phase, 'failed');
	assert.doesNotMatch(await detector.log.read(), /Restarting the detector/);
	assert.equal(await starts(), 1);
});

test(
	'a failed drain while applying settings still resumes enabled monitoring',
	posixOnly,
	async (t) => {
		const { detector, directory, settings, starts } = await fixture(t, { stopExitCode: 75 });
		await writeJson(path.join(directory, 'config.json'), { ...settings, stopExitCode: 0 });
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
		await waitFor(
			async () =>
				!(await readJson<{ enabled: boolean }>(path.join(directory, 'runtime.json')))!.enabled
		);
		process.kill(childPid, 0); // Still draining: a web crash now must not restore enabled monitoring.
		process.kill(childPid, 'SIGKILL');
		await stopped;
		const reopened = new ManagedDetector({ executable, dataDirectory: directory });
		await reopened.initialize();
		assert.equal(reopened.status().phase, 'stopped');
	}
);

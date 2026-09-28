import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { setTimeout } from 'node:timers/promises';
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
		await waitFor(() => detector.status().message.includes('Recovering'));
		assert.equal(detector.status().readiness, 'preparing');
		assert.deepEqual(detector.status().cameras, []);
		assert.match(await detector.log.read(), /Injected inference failure/);
		assert.throws(() => process.kill(originalPid, 0), { code: 'ESRCH' });

		await waitFor(() => detector.status().readiness === 'monitoring');
		assert.notEqual(await pid(), originalPid);
		assert.equal(await starts(), 2);
		assert.match(await detector.log.read(), /Injected inference failure/);
		assert.match(await detector.log.read(), /restarting the detector/);
		assert.ok(!(await detector.log.read()).includes('secret'));
		assert.deepEqual(await readJson(path.join(directory, 'config.json')), settings);
		assert.deepEqual(await readJson(path.join(directory, 'runtime.json')), {
			mode: 'auto',
			enabled: true
		});

		process.kill(await pid(), 'SIGUSR2');
		await waitFor(() => detector.status().phase === 'failed');
		assert.equal(detector.status().readiness, 'failed');
		assert.match(detector.status().message, /graphics error returned/);
		assert.equal(await starts(), 2);

		// An explicit retry starts a new monitoring session, with one recovery available.
		await detector.start('auto');
		await waitFor(() => detector.status().readiness === 'monitoring');
		process.kill(await pid(), 'SIGUSR2');
		await waitFor(() => detector.status().message.includes('Recovering'));
		await waitFor(() => detector.status().readiness === 'monitoring');
		assert.equal(await starts(), 4);
	}
);

test(
	'a later isolated MPS failure can recover after the ten-minute window',
	posixOnly,
	async (t) => {
		let now = Date.now();
		t.mock.method(Date, 'now', () => now);
		const { detector, pid } = await fixture(t);
		process.kill(await pid(), 'SIGUSR2');
		await waitFor(() => detector.status().message.includes('Recovering'));
		await waitFor(() => detector.status().readiness === 'monitoring');
		now += 10 * 60 * 1000;
		process.kill(await pid(), 'SIGUSR2');
		await waitFor(() => detector.status().message.includes('Recovering'));
		assert.equal(detector.status().readiness, 'preparing');
		await detector.stop();
	}
);

for (const disable of [true, false]) {
	test(`${disable ? 'pausing' : 'quitting'} cancels a pending recovery`, posixOnly, async (t) => {
		const { detector, directory, pid, starts } = await fixture(t);
		process.kill(await pid(), 'SIGUSR2');
		await waitFor(() => detector.status().message.includes('Recovering'));
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

test('a recovery revalidates settings and keeps a failed check visible', posixOnly, async (t) => {
	const { detector, directory, pid, starts } = await fixture(t);
	process.kill(await pid(), 'SIGUSR2');
	await waitFor(() => detector.status().message.includes('Recovering'));
	await writeJson(path.join(directory, 'config.json'), { detectors: [] });
	await waitFor(() => detector.status().phase === 'failed');
	assert.match(detector.status().message, /Add a detector/);
	assert.match(await detector.log.read(), /Injected inference failure/);
	assert.equal(await starts(), 1);
});

test(
	'pausing cancels validation during recovery and allows a later manual start',
	posixOnly,
	async (t) => {
		const { detector, directory, pid, starts } = await fixture(t);
		process.kill(await pid(), 'SIGUSR2');
		await waitFor(() => detector.status().message.includes('Recovering'));
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

for (const exitCode of [0, 1, 2]) {
	test(`exit ${exitCode} does not request GPU recovery`, posixOnly, async (t) => {
		const { detector, pid, starts } = await fixture(t, { failureExitCode: exitCode });
		process.kill(await pid(), 'SIGUSR2');
		await waitFor(() => detector.status().phase === (exitCode === 0 ? 'stopped' : 'failed'));
		assert.doesNotMatch(await detector.log.read(), /restarting the detector/);
		assert.equal(await starts(), 1);
	});
}

for (const action of ['stop', 'apply'] as const) {
	test(
		`an MPS error during ${action} never reverses the requested shutdown`,
		posixOnly,
		async (t) => {
			const { detector, starts } = await fixture(t, { stopExitCode: 75 });
			await assert.rejects(detector[action](), /stopped unexpectedly/);
			assert.equal(detector.status().phase, 'failed');
			assert.doesNotMatch(await detector.log.read(), /restarting the detector/);
			assert.equal(await starts(), 1);
		}
	);
}

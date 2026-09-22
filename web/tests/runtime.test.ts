import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout } from 'node:timers/promises';
import { ManagedDetector } from '../src/lib/server/managed-detector.ts';
import { chooseRuntime, dockerArguments } from '../src/lib/server/runtime-platform.ts';
import { readJson, writeJson } from '../src/lib/server/json-file.ts';

const executable = fileURLToPath(new URL('./fixtures/detector.mjs', import.meta.url));
const posixOnly = { skip: process.platform === 'win32' };
const config = { detectors: [{ detection: { source: 'rtsp://camera.local/live' } }] };

async function waitFor(predicate: () => boolean | Promise<boolean>) {
	for (let i = 0; i < 200; i++) {
		if (await predicate()) return;
		await setTimeout(25);
	}
	assert.fail('Expected process state was not reached');
}

for (const [platform, gpu, mode, expected] of [
	['linux', true, 'auto', 'docker'],
	['win32', true, 'auto', 'docker'],
	['darwin', false, 'auto', 'native'],
	['linux', false, 'auto', 'native'],
	['win32', false, 'auto', 'native'],
	['linux', true, 'native', 'native'],
	['win32', false, 'docker', 'docker']
] as const) {
	test(`${platform} GPU=${gpu} ${mode} selects ${expected}`, () =>
		assert.equal(chooseRuntime(mode, gpu, platform), expected));
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
	assert.equal(args.at(-1), '--control-stdin');
	assert.ok(!dockerArguments('image', 'C:\\Farm data', 'farm', 'win32').includes('--user'));
});

test('missing and malformed JSON remain different and failed reads never overwrite settings', async (t) => {
	const directory = await mkdtemp(path.join(tmpdir(), 'detector-json-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	const file = path.join(directory, 'config.json');
	assert.equal(await readJson(file), null);
	await writeFile(file, '{invalid');
	await assert.rejects(readJson(file), SyntaxError);
	assert.equal(await readFile(file, 'utf8'), '{invalid');
	await writeJson(file, config);
	assert.deepEqual(await readJson(file), config);
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
		await waitFor(() => detector.status().logs.includes('camera.local'));
		assert.equal(detector.status().phase, 'running');
		assert.ok(!detector.status().logs.includes('secret'));
		assert.equal(await readFile(path.join(directory, 'starts.txt'), 'utf8'), 'started\n');
		await detector.apply();
		await waitFor(
			async () =>
				(await readFile(path.join(directory, 'starts.txt'), 'utf8')).split('\n').length === 3
		);
		await detector.stop();
		assert.equal(await readFile(path.join(directory, 'flushed.txt'), 'utf8'), 'flushed');
		assert.equal(detector.status().phase, 'stopped');
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
	await second.initialize();
	await waitFor(() => second.status().phase === 'running');
});

test(
	'invalid configuration and crashed processes remain visible failures',
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
		await writeJson(path.join(directory, 'config.json'), { ...config, crash: true });
		await detector.start('native');
		await waitFor(() => detector.status().phase === 'failed');
		assert.match(detector.status().message, /stopped unexpectedly/);
	}
);

test(
	'Docker mode without a release image gives an actionable error without launching a container',
	posixOnly,
	async (t) => {
		const directory = await mkdtemp(path.join(tmpdir(), 'detector-docker-'));
		t.after(() => rm(directory, { recursive: true, force: true }));
		await writeJson(path.join(directory, 'config.json'), config);
		const detector = new ManagedDetector({ executable, dataDirectory: directory });
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
		await writeJson(path.join(directory, 'config.json'), { ...config, holdCheck: true });
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
		const oldPath = process.env.PATH;
		t.after(async () => {
			process.env.PATH = oldPath;
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
		const detector = new ManagedDetector({
			executable,
			dataDirectory: directory,
			dockerImage: 'example.invalid/detector@sha256:123'
		});
		await detector.start('docker');
		assert.equal(detector.status().selected, 'docker');
		assert.equal(detector.status().phase, 'failed');
		assert.match(detector.status().message, /GPU check/);
		assert.match(detector.status().logs, /CUDA driver unavailable/);
		assert.match(detector.status().helpUrl!, /^https:\/\/docs.nvidia.com/);
		assert.equal(await readJson(path.join(directory, 'runtime.json')), null);
	}
);

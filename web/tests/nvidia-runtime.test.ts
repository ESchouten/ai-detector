import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import {
	chmod,
	copyFile,
	mkdir,
	mkdtemp,
	readFile,
	readdir,
	rm,
	writeFile
} from 'node:fs/promises';
import os from 'node:os';
import { syncBuiltinESMExports } from 'node:module';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test, type TestContext } from 'node:test';
import { setTimeout } from 'node:timers/promises';
import { promisify } from 'node:util';
import {
	needsNvidiaRuntime,
	prepareNvidiaRuntime,
	selectNvidiaDevice
} from '../src/lib/server/nvidia-runtime.ts';
import { readJson, writeJson } from '../src/lib/server/json-file.ts';
import { ManagedDetector } from '../src/lib/server/managed-detector.ts';

const execute = promisify(execFile);
const config = {
	detectors: [{ detection: { source: ['video.mp4'] }, yolo: { model: 'model.pt' } }]
};
const device = {
	uuid: 'GPU-00000000-0000-0000-0000-000000000001',
	name: 'NVIDIA RTX 5060',
	capability: 12,
	driver: 580
};
const posixOnly = { skip: process.platform === 'win32' };

test('only older Windows with automatic model inference prepares a CUDA runtime', () => {
	assert.ok(needsNvidiaRuntime(config, 'win32', '10.0.19045'));
	assert.ok(needsNvidiaRuntime(config, 'win32', '10.0.22631'));
	assert.ok(!needsNvidiaRuntime(config, 'win32', '10.0.26100'));
	assert.ok(!needsNvidiaRuntime(config, 'win32', '10.0.26200'));
	assert.ok(!needsNvidiaRuntime(config, 'darwin', '24.0.0'));
	assert.ok(!needsNvidiaRuntime(config, 'linux', '6.0.0'));
	assert.ok(
		!needsNvidiaRuntime(
			{ ...config, onnx: { provider: 'CPUExecutionProvider' } },
			'win32',
			'10.0.19045'
		)
	);
	assert.ok(
		!needsNvidiaRuntime(
			{ detectors: [{ detection: { source: ['video.mp4'] } }] },
			'win32',
			'10.0.19045'
		)
	);
});

test('device discovery skips unsupported GPUs and malformed driver output', () => {
	const gpu = selectNvidiaDevice(
		`GPU-old, NVIDIA GTX 1060, 6.1, 572.83\r\n${device.uuid}, NVIDIA RTX 5060, 12.0, 580.88\r\n`
	);
	assert.deepEqual(gpu, device);
	assert.equal(selectNvidiaDevice(''), undefined);
	assert.equal(selectNvidiaDevice('NVIDIA-SMI has failed'), undefined);
	assert.equal(selectNvidiaDevice('GPU-one, NVIDIA, N/A, 580.88'), undefined);
});

async function fixture(t: TestContext) {
	const root = await mkdtemp(path.join(tmpdir(), 'nvidia bundle '));
	const bundle = path.join(root, 'nvidia-runtime');
	await mkdir(bundle);
	const data = await mkdtemp(path.join(tmpdir(), 'nvidia data '));
	const abort = new AbortController();
	const cleanup: (() => void | Promise<void>)[] = [];
	t.after(async () => {
		abort.abort();
		for (const dispose of cleanup.reverse()) await dispose();
		await rm(root, { recursive: true, force: true });
		await rm(data, { recursive: true, force: true });
	});
	await copyFile(new URL('./fixtures/nvidia-uv.cjs', import.meta.url), path.join(bundle, 'uv.exe'));
	await copyFile(
		new URL('./fixtures/nvidia-python.cjs', import.meta.url),
		path.join(bundle, 'python-fixture.cjs')
	);
	await chmod(path.join(bundle, 'uv.exe'), 0o755);
	await chmod(path.join(bundle, 'python-fixture.cjs'), 0o755);
	await copyFile(
		new URL('./fixtures/detector.mjs', import.meta.url),
		path.join(bundle, 'detector-fixture.mjs')
	);
	await writeJson(path.join(bundle, 'runtime.json'), { python: '3.12.14' });
	await writeJson(path.join(bundle, 'fixture.json'), {});
	await writeFile(path.join(bundle, 'pylock.toml'), 'locked GPU dependencies');
	const messages: string[] = [];
	const options = {
		bundleDirectory: bundle,
		dataDirectory: data,
		device,
		signal: abort.signal,
		report: (message: string) => messages.push(message),
		run: async (file: string, args: string[], timeout: number, env: NodeJS.ProcessEnv) => {
			const command = execute(file, args, { timeout, env, signal: abort.signal });
			const closed = new Promise((resolve) => command.child.once('close', resolve));
			try {
				return (await command).stdout;
			} finally {
				await closed;
			}
		}
	};
	return { root, bundle, data, abort, messages, options, cleanup };
}

async function windowsFixture(t: TestContext) {
	const fixtureData = await fixture(t);
	const { root, bundle, data } = fixtureData;
	const descriptor = Object.getOwnPropertyDescriptor(process, 'platform')!;
	const previousPath = process.env.PATH;
	fixtureData.cleanup.push(() => {
		Object.defineProperty(process, 'platform', descriptor);
		process.env.PATH = previousPath;
		t.mock.restoreAll();
		syncBuiltinESMExports();
	});
	Object.defineProperty(process, 'platform', { value: 'win32' });
	t.mock.method(os, 'release', () => '10.0.19045');
	syncBuiltinESMExports();
	await writeFile(
		path.join(root, 'nvidia-smi'),
		'#!/bin/sh\necho "' + device.uuid + ', NVIDIA RTX 5060, 12.0, 580.88"\n',
		{ mode: 0o755 }
	);
	process.env.PATH = root + path.delimiter + previousPath;
	const executable = path.join(root, 'detector.mjs');
	await copyFile(path.join(bundle, 'detector-fixture.mjs'), executable);
	await chmod(executable, 0o755);
	await writeJson(path.join(data, 'config.json'), config);
	const detector = new ManagedDetector({ executable, dataDirectory: data });
	fixtureData.cleanup.push(() => detector.stop());
	return { ...fixtureData, detector };
}

async function waitFor(predicate: () => boolean | Promise<boolean>) {
	for (let i = 0; i < 200; i++) {
		if (await predicate()) return;
		await setTimeout(25);
	}
	assert.fail('Expected runtime state was not reached');
}

test(
	'the process manager starts the cached Python environment and stops it through stdin',
	posixOnly,
	async (t) => {
		const { detector, data } = await windowsFixture(t);
		await detector.start('auto');
		await waitFor(async () => (await detector.log.read()).includes('Using NVIDIA runtime'));
		assert.equal(detector.status().phase, 'running');
		assert.match(await detector.log.read(), /GPU-00000000/);
		await detector.stop();
		assert.equal(await readFile(path.join(data, 'flushed.txt'), 'utf8'), 'flushed');
		assert.equal(detector.status().phase, 'stopped');
	}
);

test(
	'an installation failure keeps diagnostic details and offers a clean retry',
	posixOnly,
	async (t) => {
		const { detector, bundle, data } = await windowsFixture(t);
		await writeJson(path.join(bundle, 'fixture.json'), { installFailure: true });
		await detector.start('auto');
		assert.equal(detector.status().phase, 'failed');
		assert.match(detector.status().message, /NVIDIA acceleration could not be prepared/);
		assert.match(await detector.log.read(), /hash mismatch/);
		assert.equal(await readJson(path.join(data, 'runtime.json')), null);
		await writeJson(path.join(bundle, 'fixture.json'), {});
		await detector.start('auto');
		await waitFor(async () => (await detector.log.read()).includes('Using NVIDIA runtime'));
		assert.equal(detector.status().phase, 'running');
		await detector.stop();
	}
);

test(
	'pausing during NVIDIA installation cancels startup without enabling monitoring',
	posixOnly,
	async (t) => {
		const { detector, bundle, data } = await windowsFixture(t);
		await writeJson(path.join(bundle, 'fixture.json'), { holdInstall: true });
		const starting = detector.start('auto');
		await waitFor(async () => (await detector.log.read()).includes('Downloading GPU packages'));
		const pid = Number(await readFile(path.join(bundle, 'install-pid.txt'), 'utf8'));
		await detector.stop();
		await starting;
		assert.throws(() => process.kill(pid, 0), { code: 'ESRCH' });
		assert.equal(detector.status().phase, 'stopped');
		assert.equal(
			(await readJson<{ enabled: boolean }>(path.join(data, 'runtime.json')))?.enabled,
			false
		);
		await assert.rejects(readFile(path.join(data, 'starts.txt')), { code: 'ENOENT' });
	}
);

test(
	'dependencies are cached separately from app code and checked before every launch',
	posixOnly,
	async (t) => {
		const { bundle, data, messages, options } = await fixture(t);
		const first = await prepareNvidiaRuntime(options);
		assert.ok(first.file.startsWith(data));
		assert.deepEqual(first.args, ['-I', '-u', path.join(bundle, 'run.py')]);
		assert.equal(first.env?.CUDA_VISIBLE_DEVICES, device.uuid);
		const commands = (await readFile(path.join(bundle, 'commands.jsonl'), 'utf8'))
			.trim()
			.split('\n')
			.map((line) => JSON.parse(line));
		assert.equal(commands.length, 2);
		assert.equal(commands[0].args[0], 'venv');
		assert.ok(commands[1].args.includes('--require-hashes'));
		assert.ok(commands[1].args.includes('--only-binary'));
		assert.ok(commands[0].cache.startsWith(data));
		assert.match(messages.join('\n'), /Downloading and installing/);
		await writeFile(path.join(bundle, 'run.py'), '# Updated application code');
		const second = await prepareNvidiaRuntime(options);
		assert.equal(second.file, first.file);
		assert.equal(
			(await readFile(path.join(bundle, 'commands.jsonl'), 'utf8')).trim().split('\n').length,
			2
		);
		assert.equal(
			(await readFile(path.join(bundle, 'gpu-checks.txt'), 'utf8')).trim().split('\n').length,
			2
		);
		assert.deepEqual(
			await readJson(path.join(path.dirname(path.dirname(first.file)), 'ready.json')),
			{ python: '3.12.14' }
		);
		await writeFile(path.join(bundle, 'pylock.toml'), 'new pinned dependencies');
		const changed = await prepareNvidiaRuntime(options);
		assert.notEqual(changed.file, first.file);
		assert.equal((await readdir(path.join(data, 'runtimes/nvidia'))).length, 2);
	}
);

for (const failure of ['installFailure', 'gpuFailure']) {
	test(
		`${failure} remains visible and does not publish a completed environment`,
		posixOnly,
		async (t) => {
			const { bundle, data, options } = await fixture(t);
			await writeJson(path.join(bundle, 'fixture.json'), { [failure]: true });
			await assert.rejects(prepareNvidiaRuntime(options), /hash mismatch|driver is unavailable/);
			const [folder] = await readdir(path.join(data, 'runtimes/nvidia'));
			assert.equal(await readJson(path.join(data, 'runtimes/nvidia', folder, 'ready.json')), null);
			await writeJson(path.join(bundle, 'fixture.json'), {});
			await prepareNvidiaRuntime(options);
			const commands = (await readFile(path.join(bundle, 'commands.jsonl'), 'utf8'))
				.trim()
				.split('\n')
				.map((line) => JSON.parse(line));
			assert.equal(commands.filter((command) => command.args[0] === 'venv').length, 1);
			assert.equal(commands.filter((command) => command.args[0] === 'pip').length, 2);
		}
	);
}

test(
	'cancelling a download terminates uv and leaves the environment retryable',
	posixOnly,
	async (t) => {
		const { bundle, data, abort, options } = await fixture(t);
		await writeJson(path.join(bundle, 'fixture.json'), { holdInstall: true });
		const cancelled = assert.rejects(prepareNvidiaRuntime(options), { name: 'AbortError' });
		let pid: number | undefined;
		for (let i = 0; i < 100 && !pid; i++) {
			try {
				pid = Number(await readFile(path.join(bundle, 'install-pid.txt'), 'utf8'));
			} catch (error) {
				if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
			}
			if (!pid) await setTimeout(25);
		}
		assert.ok(pid, 'uv did not start');
		abort.abort();
		await cancelled;
		assert.throws(() => process.kill(pid!, 0), { code: 'ESRCH' });
		const [folder] = await readdir(path.join(data, 'runtimes/nvidia'));
		assert.equal(await readJson(path.join(data, 'runtimes/nvidia', folder, 'ready.json')), null);
	}
);

test(
	'an old NVIDIA driver gives upgrade guidance before downloading anything',
	posixOnly,
	async (t) => {
		const { data, options } = await fixture(t);
		await assert.rejects(
			prepareNvidiaRuntime({ ...options, device: { ...device, driver: 560 } }),
			/Update the NVIDIA graphics driver/
		);
		assert.deepEqual(await readdir(data), []);
	}
);

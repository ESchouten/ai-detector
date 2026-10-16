import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { readdir } from 'node:fs/promises';
import path from 'node:path';
import { test } from 'node:test';
import { promisify } from 'node:util';
import { prepareNvidiaRuntime } from '../src/lib/server/nvidia-runtime.ts';
import { readJson, writeJson } from '../src/lib/server/json-file.ts';
import { temporaryDirectory } from './support/files.ts';

const bundle = process.env.NVIDIA_RUNTIME_BUNDLE;
const execute = promisify(execFile);

// Driver 580 and newer get CUDA 13; an older driver gets CUDA 12.6.
for (const { cuda, version, capability, driverVersion } of [
	{ cuda: 13, version: '13.2', capability: 12, driverVersion: '580.88' },
	{ cuda: 12, version: '12.6', capability: 8.6, driverVersion: '566.36' }
]) {
	test(
		`the packaged Windows bootstrap installs CUDA ${cuda} and its TensorRT and refuses a missing GPU`,
		{
			skip: !bundle || process.platform !== 'win32',
			timeout: 18 * 60 * 1000
		},
		async (t) => {
			const data = await temporaryDirectory(t, 'nvidia-bootstrap-');
			const directory = path.resolve(bundle!);
			const abort = new AbortController();
			const run = async (file: string, args: string[], timeout: number, env: NodeJS.ProcessEnv) => {
				const { stdout, stderr } = await execute(file, args, {
					timeout,
					env,
					windowsHide: true,
					maxBuffer: 2 ** 20
				});
				console.info(stdout + stderr);
				return stdout;
			};
			await assert.rejects(
				prepareNvidiaRuntime({
					bundleDirectory: directory,
					dataDirectory: data,
					signal: abort.signal,
					// No GPU is available on hosted runners. A missing GPU must never publish readiness.
					device: {
						uuid: 'GPU-00000000-0000-0000-0000-000000000000',
						name: 'CI',
						capability,
						driver: Number(driverVersion.split('.')[0]),
						driverVersion
					},
					run,
					report: (message) => console.info(message)
				}),
				/NVIDIA acceleration is unavailable/
			);
			const [identity] = await readdir(path.join(data, 'runtimes/nvidia'));
			const environment = path.join(data, 'runtimes/nvidia', identity);
			assert.equal(await readJson(path.join(environment, 'ready.json')), null);
			const python = path.join(environment, 'Scripts/python.exe');
			await run(
				python,
				[
					'-I',
					'-c',
					`import torch, torchvision, onnxruntime; assert torch.version.cuda == "${version}"; assert "CUDAExecutionProvider" in onnxruntime.get_available_providers(); torchvision.ops.nms(torch.zeros((1,4)), torch.ones(1), 0.5)`
				],
				60000,
				process.env
			);
			const config = path.join(data, 'config.json');
			await writeJson(config, { detectors: [{ detection: { source: ['video.mp4'] } }] });
			const output = await run(
				python,
				['-I', path.join(directory, 'run.py'), '--config', config, '--check-config'],
				60000,
				process.env
			);
			assert.match(output, /Configuration valid: 1 detector/);
			await run(
				path.join(directory, 'uv.exe'),
				[
					'pip',
					'install',
					'--no-config',
					'--python',
					python,
					'--require-hashes',
					'--only-binary',
					':all:',
					'--no-binary',
					`tensorrt-cu${cuda}`,
					'-r',
					path.join(directory, `pylock.tensorrt-cuda${cuda}.toml`)
				],
				600000,
				{ ...process.env, NVIDIA_TENSORRT_DISABLE_INTERNAL_PIP: '1' }
			);
			await run(
				python,
				[
					'-I',
					'-c',
					`import torch, tensorrt; assert torch.version.cuda == "${version}"; assert tensorrt.__version__ == "10.16.1.11"`
				],
				60000,
				process.env
			);
		}
	);
}

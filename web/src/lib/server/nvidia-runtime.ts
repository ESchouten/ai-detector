import { execFile } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync } from 'node:fs';
import { mkdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { promisify } from 'node:util';
import type { Config } from '../schema.ts';
import { readJson, writeJson } from './json-file.ts';
import { SetupError } from './runtime-platform.ts';

const execute = promisify(execFile);
const NVIDIA_DRIVER_HELP = 'https://www.nvidia.com/drivers/';

interface NvidiaDevice {
	uuid: string;
	name: string;
	driver: number;
	capability: number;
}

export interface DetectorCommand {
	file: string;
	args: string[];
	env?: NodeJS.ProcessEnv;
}

interface Preparation {
	bundleDirectory: string;
	dataDirectory: string;
	device: NvidiaDevice;
	signal: AbortSignal;
	run: (file: string, args: string[], timeout: number, env: NodeJS.ProcessEnv) => Promise<string>;
	report: (message: string) => void;
}

/** Newer Windows uses the existing Windows ML route; explicit provider choices win. */
export function needsNvidiaRuntime(config: Config, platform: string, release: string): boolean {
	return (
		platform === 'win32' &&
		Number(release.split('.')[2]) < 26100 &&
		!config.onnx?.provider &&
		config.detectors.some((detector) => detector.yolo != null)
	);
}

export function selectNvidiaDevice(output: string): NvidiaDevice | undefined {
	return output
		.trim()
		.split('\n')
		.map((line) => {
			const [uuid, name, capability, driver] = line.split(',').map((part) => part.trim());
			return { uuid, name, capability: Number(capability), driver: Number(driver?.split('.')[0]) };
		})
		.find(
			(device) =>
				device.uuid && device.name && device.capability >= 7.5 && Number.isFinite(device.driver)
		);
}

export async function discoverNvidia(signal: AbortSignal): Promise<NvidiaDevice | undefined> {
	const command = execute(
		'nvidia-smi',
		['--query-gpu=uuid,name,compute_cap,driver_version', '--format=csv,noheader,nounits'],
		{ signal, timeout: 5000, windowsHide: true }
	);
	const closed = new Promise((resolve) => command.child.once('close', resolve));
	try {
		const { stdout } = await command;
		return selectNvidiaDevice(stdout);
	} catch {
		signal.throwIfAborted();
		// No working NVIDIA driver/tool means no usable CUDA device to prepare.
		return undefined;
	} finally {
		await closed;
	}
}

/** uv owns downloads/installations; a completion marker is published only after a GPU check. */
export async function prepareNvidiaRuntime(options: Preparation): Promise<DetectorCommand> {
	const { bundleDirectory, dataDirectory, device, signal, run, report } = options;
	if (device.driver < 572) {
		throw new SetupError(
			'Update the NVIDIA graphics driver, then try again to enable GPU acceleration.',
			NVIDIA_DRIVER_HELP
		);
	}
	const manifest = await readJson<{ python: string }>(path.join(bundleDirectory, 'runtime.json'));
	if (!manifest)
		throw new SetupError('The NVIDIA runtime files are missing. Reinstall AI Detector.');
	const lock = path.join(bundleDirectory, 'pylock.toml');
	const identity = createHash('sha256')
		.update(manifest.python)
		.update(await readFile(lock))
		.digest('hex')
		.slice(0, 20);
	const directory = path.join(dataDirectory, 'runtimes', 'nvidia', identity);
	const python = path.join(directory, 'Scripts', 'python.exe');
	const ready = path.join(directory, 'ready.json');
	const prepared = existsSync(ready);
	const uv = path.join(bundleDirectory, 'uv.exe');
	const env = {
		...process.env,
		CUDA_VISIBLE_DEVICES: device.uuid,
		UV_PYTHON_INSTALL_DIR: path.join(dataDirectory, 'runtimes', 'python'),
		UV_CACHE_DIR: path.join(dataDirectory, 'cache', 'uv'),
		UV_PYTHON_PREFERENCE: 'only-managed',
		UV_LINK_MODE: 'hardlink',
		MPLCONFIGDIR: path.join(dataDirectory, 'cache', 'matplotlib')
	};
	await mkdir(path.dirname(directory), { recursive: true });
	if (!prepared) {
		report('Preparing NVIDIA acceleration. The first download may take several minutes…');
		if (!existsSync(python)) {
			await run(uv, ['venv', '--no-config', '--python', manifest.python, directory], 300000, env);
		}
		report('Downloading and installing NVIDIA acceleration…');
		await run(
			uv,
			[
				'pip',
				'sync',
				'--no-config',
				'--python',
				python,
				'--only-binary',
				':all:',
				'--require-hashes',
				lock
			],
			1800000,
			env
		);
	}
	signal.throwIfAborted();
	report('Checking NVIDIA acceleration…');
	const command = { file: python, args: ['-I', '-u', path.join(bundleDirectory, 'run.py')], env };
	await run(command.file, [...command.args, '--check-cuda'], 60000, env);
	signal.throwIfAborted();
	if (!prepared) await writeJson(ready, { python: manifest.python });
	return command;
}

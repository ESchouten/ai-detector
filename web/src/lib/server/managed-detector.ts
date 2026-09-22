import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { mkdir, rm } from 'node:fs/promises';
import path from 'node:path';
import type { RuntimeMode, RuntimeStatus } from '../runtime.ts';
import { readJson, writeJson } from './json-file.ts';
import {
	checkDocker,
	chooseRuntime,
	dockerArguments,
	hasNvidiaGpu,
	NVIDIA_HELP,
	SetupError
} from './runtime-platform.ts';

interface Settings {
	mode: RuntimeMode;
	enabled: boolean;
}
interface Options {
	executable: string;
	dataDirectory: string;
	dockerImage?: string;
}

function redact(text: string): string {
	return text
		.replace(/(\w+:\/\/)[^\s/@]+@/g, '$1***@')
		.replace(/([?&](?:token|key|password|api_key)=)[^&\s]+/gi, '$1***');
}

/** One owner for the detector process. Commands are serialized; polling has no side effects. */
export class ManagedDetector {
	private child: ChildProcessWithoutNullStreams | null = null;
	private finished: Promise<void> = Promise.resolve();
	private operation: Promise<unknown> = Promise.resolve();
	private startup: AbortController | null = null;
	private settings: Settings = { mode: 'auto', enabled: false };
	private state: RuntimeStatus;
	private readonly settingsPath: string;
	private readonly containerName: string;
	private readonly options: Options;

	constructor(options: Options) {
		this.options = options;
		this.settingsPath = path.join(options.dataDirectory, 'runtime.json');
		this.containerName =
			'ai-detector-' +
			createHash('sha256').update(options.dataDirectory).digest('hex').slice(0, 12);
		this.state = {
			managed: true,
			mode: 'auto',
			selected: null,
			phase: 'stopped',
			message: 'Ready to set up your camera.',
			logs: '',
			dataDirectory: options.dataDirectory
		};
	}

	status(): RuntimeStatus {
		return { ...this.state, logs: redact(this.state.logs) };
	}

	private enqueue<T>(action: () => Promise<T>): Promise<T> {
		const result = this.operation.then(action);
		this.operation = result.catch(() => undefined);
		return result;
	}

	async initialize(): Promise<void> {
		const saved = await readJson<Settings>(this.settingsPath);
		if (saved) {
			if (
				!['auto', 'native', 'docker'].includes(saved.mode) ||
				typeof saved.enabled !== 'boolean'
			) {
				throw new SetupError(
					'Saved startup settings are invalid. Restore runtime.json from a backup.'
				);
			}
			this.settings = saved;
			this.state.mode = saved.mode;
		}
		if (this.settings.enabled) await this.start(this.settings.mode);
	}

	async validate(config: unknown, signal?: AbortSignal): Promise<void> {
		await mkdir(this.options.dataDirectory, { recursive: true });
		const file = path.join(this.options.dataDirectory, `check-${randomUUID()}.json`);
		try {
			await writeJson(file, config);
			await this.runCheck(
				this.options.executable,
				['--config', file, '--check-config'],
				30000,
				signal
			);
		} finally {
			await rm(file, { force: true });
		}
	}

	start(mode: RuntimeMode): Promise<void> {
		return this.enqueue(async () => {
			if (this.child) return;
			const startup = new AbortController();
			this.startup = startup;
			this.state = {
				...this.state,
				phase: 'checking',
				mode,
				helpUrl: undefined,
				message: 'Checking this computer…',
				logs: ''
			};
			try {
				const config = await readJson(path.join(this.options.dataDirectory, 'config.json'));
				if (!config) throw new SetupError('Add a camera and choose what to detect first.');
				await this.validate(config, startup.signal);
				const selected = chooseRuntime(
					mode,
					mode === 'auto' && (await hasNvidiaGpu()),
					process.platform
				);
				this.state.selected = selected;
				startup.signal.throwIfAborted();
				const command = await this.prepare(selected, startup.signal);
				startup.signal.throwIfAborted();
				this.settings = { mode, enabled: true };
				await writeJson(this.settingsPath, this.settings);
				this.launch(command.file, command.args);
			} catch (error) {
				if (startup.signal.aborted) {
					this.state.phase = 'stopped';
					this.state.message = 'Start cancelled.';
				} else this.fail(error);
			} finally {
				this.startup = null;
			}
		});
	}

	private async prepare(
		selected: 'native' | 'docker',
		signal: AbortSignal
	): Promise<{ file: string; args: string[] }> {
		if (selected === 'native') {
			return {
				file: this.options.executable,
				args: [
					'--config',
					path.join(this.options.dataDirectory, 'config.json'),
					'--data-dir',
					this.options.dataDirectory,
					'--control-stdin'
				]
			};
		}
		const image = this.options.dockerImage;
		if (!image)
			throw new SetupError(
				'This download does not include a Docker image reference. Choose “On this computer” or download a complete application release.'
			);
		await checkDocker(process.platform);
		signal.throwIfAborted();
		this.state.message =
			'Downloading and checking GPU support. The first download can take several minutes.';
		try {
			await this.runCheck(
				'docker',
				[
					'run',
					'--rm',
					'--gpus',
					'all',
					image,
					'python3',
					'-c',
					'import torch; assert torch.cuda.is_available(), "CUDA is unavailable"; print(torch.ones(1, device="cuda").cpu())'
				],
				900000,
				signal
			);
		} catch {
			throw new SetupError(
				'Docker could not run the NVIDIA GPU check. Check your internet connection, NVIDIA driver and Docker GPU support, then try again. You can also choose “On this computer”.',
				process.platform === 'win32' ? 'https://docs.docker.com/desktop/features/gpu/' : NVIDIA_HELP
			);
		}
		const user =
			process.getuid && process.getgid ? `${process.getuid()}:${process.getgid()}` : undefined;
		return {
			file: 'docker',
			args: dockerArguments(
				image,
				this.options.dataDirectory,
				this.containerName,
				process.platform,
				user
			)
		};
	}

	private append(chunk: Buffer): void {
		this.state.logs = (this.state.logs + chunk.toString()).slice(-16000);
	}

	private runCheck(
		file: string,
		args: string[],
		timeout: number,
		signal?: AbortSignal
	): Promise<void> {
		return new Promise((resolve, reject) => {
			const child = spawn(file, args, {
				cwd: this.options.dataDirectory,
				windowsHide: true,
				timeout,
				signal,
				stdio: ['ignore', 'pipe', 'pipe']
			});
			let output = '';
			child.stdout.on('data', (chunk: Buffer) => {
				this.append(chunk);
				output = (output + chunk.toString()).slice(-4000);
			});
			child.stderr.on('data', (chunk: Buffer) => {
				this.append(chunk);
				output = (output + chunk.toString()).slice(-4000);
			});
			child.on('error', () =>
				reject(
					new SetupError(
						'Could not open the detector. Extract the complete download and keep its files together.'
					)
				)
			);
			child.on('close', (code) =>
				code === 0
					? resolve()
					: reject(
							new SetupError(
								redact(output.trim()) || 'The detector check did not finish. Please try again.'
							)
						)
			);
		});
	}

	private launch(file: string, args: string[]): void {
		this.state.phase = 'starting';
		this.state.message = 'Starting the detector…';
		const child = spawn(file, args, {
			cwd: this.options.dataDirectory,
			windowsHide: true,
			stdio: 'pipe',
			env: { ...process.env, PYTHONUNBUFFERED: '1' }
		});
		this.child = child;
		child.stdin.on('error', (error: NodeJS.ErrnoException) => {
			if (error.code !== 'EPIPE') this.fail(error);
		});
		child.stdout.on('data', (chunk: Buffer) => this.append(chunk));
		child.stderr.on('data', (chunk: Buffer) => this.append(chunk));
		child.on('spawn', () => {
			this.state.phase = 'running';
			this.state.message =
				'The detector process is running. The first start may take several minutes to download and prepare the model.';
		});
		child.on('error', (error) => this.fail(error));
		this.finished = new Promise((resolve) =>
			child.on('close', (code) => {
				this.child = null;
				if (code === 0) {
					this.state.phase = 'stopped';
					this.state.message = 'Detector stopped.';
				} else if (this.state.phase !== 'failed')
					this.fail(
						new SetupError(
							'The detector stopped unexpectedly. Check the details below, then try again.'
						)
					);
				resolve();
			})
		);
	}

	stop(disable = true): Promise<void> {
		this.startup?.abort();
		return this.enqueue(async () => {
			if (disable) this.settings.enabled = false;
			await this.stopChild();
			if (disable) await writeJson(this.settingsPath, this.settings);
		});
	}

	private async stopChild(): Promise<void> {
		const child = this.child;
		if (!child) return;
		this.state.phase = 'stopping';
		this.state.message = 'Finishing detections and stopping…';
		child.stdin.end('stop\n');
		const timer = setTimeout(() => {
			this.fail(
				new SetupError(
					'The detector did not finish shutting down within 30 seconds. It was forced to stop; the last detection may be incomplete.'
				)
			);
			if (this.state.selected === 'docker') {
				void this.runCheck('docker', ['stop', '--time', '5', this.containerName], 10000).catch(
					(error) => this.fail(error)
				);
			}
			child.kill('SIGKILL');
		}, 30000);
		try {
			await this.finished;
		} finally {
			clearTimeout(timer);
		}
	}

	async apply(): Promise<void> {
		if (this.settings.enabled) {
			await this.stop(false);
			await this.start(this.settings.mode);
		}
	}

	fail(error: unknown): void {
		this.state.phase = 'failed';
		this.state.message =
			error instanceof Error ? redact(error.message) : 'The detector could not start.';
		this.state.helpUrl = error instanceof SetupError ? error.helpUrl : undefined;
	}
}

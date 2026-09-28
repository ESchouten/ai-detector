import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { existsSync } from 'node:fs';
import { mkdir, rm } from 'node:fs/promises';
import { release } from 'node:os';
import path from 'node:path';
import { createInterface } from 'node:readline';
import { setTimeout as delay } from 'node:timers/promises';
import type { RuntimeMode, RuntimeStatus } from '../runtime.ts';
import type { AppConfig, Config } from '../schema.ts';
import { readJson, writeJson } from './json-file.ts';
import {
	discoverNvidia,
	needsNvidiaRuntime,
	prepareNvidiaRuntime,
	type DetectorCommand
} from './nvidia-runtime.ts';
import { sanitizeTextForLogs as redact } from './runtime-logs.ts';
import { RuntimeProgress, STATUS_PREFIX } from './runtime-status.ts';
import {
	checkDocker,
	chooseRuntime,
	dockerArguments,
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

// Contract with aidetector.cli: only a native MPS inference failure exits with 75.
const MPS_FAILURE_EXIT_CODE = 75;
const RECOVERY_WINDOW_MS = 10 * 60 * 1000;

/** One owner for the detector process. Commands are serialized; polling has no side effects. */
export class ManagedDetector {
	private child: ChildProcessWithoutNullStreams | null = null;
	private finished: Promise<number | null> = Promise.resolve(0);
	private operation: Promise<unknown> = Promise.resolve();
	private startup = new AbortController();
	private lastRecovery: number | null = null;
	private settings: Settings = { mode: 'auto', enabled: false };
	private state: RuntimeStatus;
	private readonly settingsPath: string;
	private readonly containerName: string;
	private readonly options: Options;
	private progress = new RuntimeProgress();

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
			dataDirectory: options.dataDirectory,
			readiness: 'idle',
			cameras: []
		};
	}

	status(): RuntimeStatus {
		const progress = this.progress.snapshot();
		const readiness =
			this.state.phase === 'failed'
				? 'failed'
				: this.state.phase === 'stopped' || this.state.phase === 'stopping'
					? 'idle'
					: progress.readiness;
		const cameras = progress.cameras.map((camera) => ({
			...camera,
			...(readiness === 'failed' ? { state: 'failed' as const } : {}),
			...(readiness === 'idle' ? { state: 'paused' as const } : {})
		}));
		const message =
			readiness === 'monitoring'
				? `Monitoring ${cameras.length} camera${cameras.length === 1 ? '' : 's'}.`
				: readiness === 'degraded'
					? 'Monitoring needs attention.'
					: readiness === 'failed'
						? (this.progress.preparationFailure ?? this.state.message)
						: this.state.message;
		return {
			...this.state,
			message,
			readiness,
			cameras,
			logs: redact(this.state.logs),
			preparation: readiness === 'preparing' ? this.progress.preparation : undefined,
			notice: this.progress.notice
		};
	}

	private enqueue<T>(action: () => Promise<T>): Promise<T> {
		const result = this.operation.then(action);
		this.operation = result.catch(() => undefined);
		return result;
	}

	async refreshMetadata(): Promise<void> {
		const app = await readJson<AppConfig>(path.join(this.options.dataDirectory, 'app.json'));
		if (app) this.progress.updateMetadata(app);
	}

	initialize(): Promise<void> {
		const signal = this.startup.signal;
		return this.enqueue(async () => {
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
			if (this.settings.enabled) await this.startChild(this.settings.mode, signal);
		});
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
		const signal = this.startup.signal;
		return this.enqueue(() => {
			if (!this.child) this.lastRecovery = null;
			return this.startChild(mode, signal);
		});
	}

	private async startChild(
		mode: RuntimeMode,
		signal: AbortSignal,
		recovering = false
	): Promise<void> {
		if (this.child || signal.aborted) return;
		this.progress = new RuntimeProgress();
		this.state = {
			...this.state,
			phase: 'checking',
			mode,
			selected: null,
			helpUrl: undefined,
			message: 'Checking this computer…',
			logs: recovering ? this.state.logs : ''
		};
		try {
			const config = await readJson<Config>(path.join(this.options.dataDirectory, 'config.json'));
			if (!config) throw new SetupError('Add a camera and choose what to detect first.');
			await this.validate(config, signal);
			const app = await readJson<AppConfig>(path.join(this.options.dataDirectory, 'app.json'));
			this.progress.configure(
				config,
				app ?? { streams: [], telegrams: [], detectors: [] },
				this.options.dataDirectory
			);
			const selected = chooseRuntime(mode);
			this.state.selected = selected;
			signal.throwIfAborted();
			const command = await this.prepare(selected, config, signal);
			signal.throwIfAborted();
			this.settings = { mode, enabled: true };
			await writeJson(this.settingsPath, this.settings);
			signal.throwIfAborted();
			this.launch(command, signal);
		} catch (error) {
			if (signal.aborted) {
				this.state.phase = 'stopped';
				this.state.message = 'Start cancelled.';
			} else this.fail(error);
		}
	}

	private async prepare(
		selected: 'native' | 'docker',
		config: Config,
		signal: AbortSignal
	): Promise<DetectorCommand> {
		if (selected === 'native') {
			const command = await this.nativeCommand(config, signal);
			return {
				...command,
				args: [
					...command.args,
					'--config',
					path.join(this.options.dataDirectory, 'config.json'),
					'--data-dir',
					this.options.dataDirectory,
					'--control-stdin',
					'--status-json',
					'--live-preview'
				]
			};
		}
		const image = this.options.dockerImage;
		if (!image)
			throw new SetupError(
				'This download does not include a Docker image reference. Choose “On this computer” or download a complete application release.'
			);
		await checkDocker(process.platform, signal);
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

	private async nativeCommand(config: Config, signal: AbortSignal): Promise<DetectorCommand> {
		const bundleDirectory = path.join(path.dirname(this.options.executable), 'nvidia-runtime');
		if (needsNvidiaRuntime(config, process.platform, release()) && existsSync(bundleDirectory)) {
			const device = await discoverNvidia(signal);
			if (device) {
				try {
					return await prepareNvidiaRuntime({
						bundleDirectory,
						dataDirectory: this.options.dataDirectory,
						device,
						signal,
						run: (file, args, timeout, env) => this.runCheck(file, args, timeout, signal, env),
						report: (message) => {
							this.state.message = message;
						}
					});
				} catch (error) {
					signal.throwIfAborted();
					if (error instanceof SetupError && error.helpUrl) throw error;
					this.append(Buffer.from(`\nNVIDIA preparation failed: ${String(error)}\n`));
					throw new SetupError(
						'NVIDIA acceleration could not be prepared. Check your internet connection and graphics driver, then try again. Details are available below.'
					);
				}
			}
		}
		return { file: this.options.executable, args: [] };
	}

	private append(chunk: Buffer): void {
		this.state.logs = (this.state.logs + chunk.toString()).slice(-16000);
	}

	private runCheck(
		file: string,
		args: string[],
		timeout: number,
		signal?: AbortSignal,
		env?: NodeJS.ProcessEnv
	): Promise<string> {
		return new Promise((resolve, reject) => {
			const child = spawn(file, args, {
				cwd: this.options.dataDirectory,
				windowsHide: true,
				timeout,
				signal,
				env,
				killSignal: 'SIGKILL',
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
			let startError: Error | undefined;
			child.once('error', (error) => {
				startError = error;
			});
			// Abort emits an error before the process has exited. Keep the temporary
			// configuration and this operation alive until its streams are closed.
			child.once('close', (code) => {
				if (signal?.aborted) reject(signal.reason);
				else if (startError)
					reject(
						new SetupError(
							'Could not open the detector. Extract the complete download and keep its files together.'
						)
					);
				else if (code === 0) resolve(output);
				else
					reject(
						new SetupError(
							redact(output.trim()) || 'The detector check did not finish. Please try again.'
						)
					);
			});
		});
	}

	private launch(command: DetectorCommand, signal: AbortSignal): void {
		this.state.phase = 'starting';
		this.state.message = 'Starting the detector…';
		const child = spawn(command.file, command.args, {
			cwd: this.options.dataDirectory,
			windowsHide: true,
			stdio: 'pipe',
			env: { ...process.env, ...command.env, PYTHONUNBUFFERED: '1' }
		});
		this.child = child;
		child.stdin.on('error', (error: NodeJS.ErrnoException) => {
			if (error.code !== 'EPIPE') this.fail(error);
		});
		const records = createInterface({ input: child.stdout, crlfDelay: Infinity });
		records.on('line', (line) => {
			if (line.startsWith(STATUS_PREFIX)) this.progress.accept(line);
			else this.append(Buffer.from(line + '\n'));
		});
		child.stderr.on('data', (chunk: Buffer) => this.append(chunk));
		child.on('spawn', () => {
			if (this.state.phase !== 'starting') return;
			this.state.phase = 'running';
			this.state.message =
				'Preparing detection and connecting cameras. Monitoring will be confirmed after frames are processed.';
		});
		child.on('error', (error) => this.fail(error));
		this.finished = new Promise((resolve) =>
			child.on('close', (code) => {
				records.close();
				this.child = null;
				if (
					code === MPS_FAILURE_EXIT_CODE &&
					this.state.selected === 'native' &&
					this.state.phase !== 'stopping' &&
					this.state.phase !== 'failed' &&
					!signal.aborted
				) {
					this.recoverMps(signal);
				} else if (code === 0 && this.state.phase !== 'failed') {
					this.state.phase = 'stopped';
					this.state.message = 'Detector stopped.';
				} else if (this.state.phase !== 'failed')
					this.fail(
						new SetupError(
							this.progress.preparationFailure ??
								'The detector stopped unexpectedly. Check the details below, then try again.'
						)
					);
				resolve(code);
			})
		);
	}

	private recoverMps(signal: AbortSignal): void {
		const now = Date.now();
		if (this.lastRecovery !== null && now - this.lastRecovery < RECOVERY_WINDOW_MS) {
			this.fail(
				new SetupError(
					'The graphics error returned after restarting. Monitoring has stopped. Check the details below, then try again.'
				)
			);
			return;
		}
		this.lastRecovery = now;
		this.progress = new RuntimeProgress();
		this.state.phase = 'starting';
		this.state.message = 'Recovering from a graphics error. Restarting monitoring…';
		this.append(Buffer.from('\nApple GPU error: restarting the detector in 2 seconds.\n'));
		void this.enqueue(async () => {
			try {
				await delay(2000, undefined, { signal });
				await this.startChild(this.settings.mode, signal, true);
			} catch (error) {
				if (signal.aborted) {
					this.state.phase = 'stopped';
					this.state.message = 'Restart cancelled.';
				} else this.fail(error);
			}
		});
	}

	stop(disable = true): Promise<void> {
		// A stop cancels both the active check and starts already waiting in the queue.
		this.startup.abort();
		this.startup = new AbortController();
		return this.enqueue(async () => {
			if (disable) this.settings.enabled = false;
			try {
				await this.stopChild();
			} finally {
				if (disable) await writeJson(this.settingsPath, this.settings);
			}
		});
	}

	private async stopChild(): Promise<void> {
		const child = this.child;
		if (!child) return;
		this.state.phase = 'stopping';
		this.state.message = 'Finishing detections and stopping…';
		child.stdin.end('stop\n');
		let forcedStop: Promise<void> | undefined;
		let timedOut = false;
		const timer = setTimeout(() => {
			timedOut = true;
			this.fail(
				new SetupError(
					'The detector did not finish shutting down within 30 seconds. It was forced to stop; the last detection may be incomplete.'
				)
			);
			if (this.state.selected === 'docker') {
				forcedStop = this.runCheck('docker', ['stop', '--time', '5', this.containerName], 10000)
					.then(() => undefined)
					.catch((error) => this.fail(error));
			}
			child.kill('SIGKILL');
		}, 30000);
		try {
			const code = await this.finished;
			await forcedStop;
			if (code !== 0 || timedOut) throw new SetupError(this.state.message);
		} finally {
			clearTimeout(timer);
		}
	}

	apply(): Promise<void> {
		const signal = this.startup.signal;
		return this.enqueue(async () => {
			if (!this.settings.enabled || signal.aborted) return;
			await this.stopChild();
			await this.startChild(this.settings.mode, signal);
		});
	}

	fail(error: unknown): void {
		this.state.phase = 'failed';
		this.state.message =
			error instanceof Error ? redact(error.message) : 'The detector could not start.';
		this.state.helpUrl = error instanceof SetupError ? error.helpUrl : undefined;
	}
}

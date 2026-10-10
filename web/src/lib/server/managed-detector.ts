import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import path from 'node:path';
import { createInterface } from 'node:readline';
import { setTimeout as delay } from 'node:timers/promises';
import { plural } from '../format.ts';
import type { RuntimeStatus } from '../runtime.ts';
import type { AppConfig, Config, LlmConnection } from '../schema.ts';
import { readJson } from './json-file.ts';
import { monitoringEnabled, setMonitoringEnabled } from './monitoring-flag.ts';
import { DetectorLog } from './detector-log.ts';
import type { DetectorCommand } from './nvidia-runtime.ts';
import { DetectorPreparation, type DetectorOptions } from './detector-preparation.ts';
import { sanitizeTextForLogs as redact } from './runtime-logs.ts';
import { RuntimeProgress, STATUS_PREFIX } from './runtime-status.ts';
import { SetupError } from './runtime-platform.ts';
import { serialQueue } from './serial.ts';

/** Whether monitoring resumes with the application: `monitoring` in app.json. */
interface Settings {
	enabled: boolean;
}

const INITIAL_RESTART_DELAY_MS = 2000;
const MAX_RESTART_DELAY_MS = 30000;
const STABLE_RUN_MS = 10 * 60 * 1000;

/** One owner for the detector process. Commands are serialized; polling has no side effects. */
export class ManagedDetector {
	readonly log: DetectorLog;
	private child: ChildProcessWithoutNullStreams | null = null;
	private stoppingChild = false;
	private finished: Promise<number | null> = Promise.resolve(0);
	private readonly enqueue = serialQueue();
	private startup = new AbortController();
	private restartDelay = INITIAL_RESTART_DELAY_MS;
	private settings: Settings = { enabled: false };
	private state: RuntimeStatus;
	private readonly appPath: string;
	private readonly preparation: DetectorPreparation;
	private readonly options: DetectorOptions;
	private progress = new RuntimeProgress();

	constructor(options: DetectorOptions) {
		this.options = options;
		this.log = new DetectorLog(options.dataDirectory);
		this.appPath = path.join(options.dataDirectory, 'app.json');
		this.preparation = new DetectorPreparation(options, this.log, (message) => {
			this.state.message = message;
		});
		this.state = {
			managed: true,
			phase: 'stopped',
			message: 'Ready to set up your camera.',
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
				? plural(cameras.length, ['Monitoring # camera.', 'Monitoring # cameras.'])
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
			preparation: readiness === 'preparing' ? this.progress.preparation : undefined,
			notice: this.progress.notice,
			issues: this.progress.issues,
			backends: this.progress.backends
		};
	}

	async refreshMetadata(): Promise<void> {
		const app = await readJson<AppConfig>(this.appPath);
		if (app) this.progress.updateMetadata(app);
	}

	initialize(): Promise<void> {
		const signal = this.startup.signal;
		return this.enqueue(async () => {
			this.settings = { enabled: await monitoringEnabled(this.appPath) };
			if (this.settings.enabled) {
				await this.log.resume();
				await this.startChild(signal, true);
			}
		});
	}

	validate(config: unknown, signal?: AbortSignal): Promise<void> {
		return this.preparation.validate(config, signal);
	}
	testLlm(connection: LlmConnection, signal?: AbortSignal): Promise<void> {
		return this.preparation.testLlm(connection, signal);
	}

	start(): Promise<void> {
		const signal = this.startup.signal;
		return this.enqueue(() => {
			if (!this.child) this.restartDelay = INITIAL_RESTART_DELAY_MS;
			return this.startChild(signal);
		});
	}

	whileStopped<T>(operation: () => Promise<T>): Promise<T> {
		return this.enqueue(() => {
			if (this.settings.enabled || this.child)
				throw new SetupError('Pause monitoring before clearing the model cache.');
			return operation();
		});
	}

	private async startChild(signal: AbortSignal, preserveLog = false): Promise<void> {
		if (this.child || signal.aborted) return;
		if (!preserveLog) this.log.begin();
		this.progress = new RuntimeProgress();
		this.state = {
			...this.state,
			phase: 'checking',
			helpUrl: undefined,
			message: 'Checking this computer…'
		};
		try {
			const config = await readJson<Config>(path.join(this.options.dataDirectory, 'config.json'));
			if (!config) throw new SetupError('Add a camera and choose what to detect first.');
			await this.validate(config, signal);
			const app = await readJson<AppConfig>(this.appPath);
			this.progress.configure(
				config,
				app ?? { streams: [], telegrams: [], llms: [], detectors: [] },
				this.options.dataDirectory
			);
			signal.throwIfAborted();
			const command = await this.preparation.command(config, signal);
			signal.throwIfAborted();
			this.settings = { enabled: true };
			await setMonitoringEnabled(this.appPath, true);
			signal.throwIfAborted();
			this.launch(command, signal);
		} catch (error) {
			if (signal.aborted) {
				this.state.phase = 'stopped';
				this.state.message = 'Start cancelled.';
			} else {
				this.fail(error);
				if (this.settings.enabled) this.scheduleRestart(signal);
			}
		}
	}

	private launch(command: DetectorCommand, signal: AbortSignal): void {
		const startedAt = Date.now();
		this.state.phase = 'starting';
		this.state.message = 'Starting the detector…';
		const child = spawn(command.file, command.args, {
			cwd: this.options.dataDirectory,
			windowsHide: true,
			stdio: 'pipe',
			env: { ...process.env, ...command.env, PYTHONUNBUFFERED: '1' }
		});
		this.child = child;
		this.stoppingChild = false;
		let lastCheck = Date.now();
		let resumeGraceUntil = 0;
		let recovering = false;
		const watchdog = setInterval(() => {
			const now = Date.now();
			// Give cameras and GPU drivers time to recover after suspend or an event-loop pause.
			if (now - lastCheck > 30000) resumeGraceUntil = now + 120000;
			lastCheck = now;
			if (recovering || this.stoppingChild || signal.aborted || now < resumeGraceUntil) return;
			const stalled = this.progress.stalledDetector(now);
			if (!stalled) return;
			recovering = true;
			void this.enqueue(async () => {
				if (this.child === child && !this.stoppingChild)
					// The reason is written to the log, which stays in English.
					await this.restartChild(
						signal,
						/* @wc-ignore */ `${stalled} stopped processing fresh camera frames`
					);
			}).catch((error) => this.fail(error));
		}, 5000);
		watchdog.unref();
		child.stdin.on('error', (error: NodeJS.ErrnoException) => {
			if (error.code !== 'EPIPE') this.fail(error);
		});
		const records = createInterface({ input: child.stdout, crlfDelay: Infinity });
		records.on('line', (line) => {
			if (!line.startsWith(STATUS_PREFIX)) {
				this.log.append(line + '\n');
				return;
			}
			const event = this.progress.accept(line);
			if (event?.event === 'models_ready')
				void this.enqueue(async () => {
					// Ignore duplicate/stale requests from a process already being replaced.
					if (this.child !== child || this.stoppingChild) return;
					await this.restartChild(signal, /* @wc-ignore */ 'TensorRT models are ready');
				}).catch((error) => this.fail(error));
		});
		createInterface({ input: child.stderr, crlfDelay: Infinity }).on('line', (line) =>
			this.log.append(line + '\n')
		);
		child.on('spawn', () => {
			if (this.state.phase !== 'starting') return;
			this.state.phase = 'running';
			this.state.message =
				'Preparing detection and connecting cameras. Monitoring will be confirmed after frames are processed.';
		});
		child.on('error', (error) => this.fail(error));
		this.finished = new Promise((resolve) =>
			child.on('close', (code, exitSignal) => {
				clearInterval(watchdog);
				records.close();
				this.log.append(`${new Date().toISOString()} Detector exited: ${exitSignal ?? code}\n`);
				this.child = null;
				if (this.settings.enabled && !this.stoppingChild && !signal.aborted) {
					if (Date.now() - startedAt >= STABLE_RUN_MS) this.restartDelay = INITIAL_RESTART_DELAY_MS;
					if (this.state.phase !== 'failed')
						this.fail(
							new SetupError(
								this.progress.preparationFailure ??
									`The detector stopped unexpectedly (${exitSignal ?? code}).`
							)
						);
					this.scheduleRestart(signal);
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
				void this.log.flush().then(() => resolve(code));
			})
		);
	}

	private scheduleRestart(signal: AbortSignal): void {
		const wait = this.restartDelay;
		this.restartDelay = Math.min(wait * 2, MAX_RESTART_DELAY_MS);
		this.progress = new RuntimeProgress();
		this.state.phase = 'starting';
		const restarting = `Restarting monitoring in ${wait / 1000} seconds…`;
		this.state.message = `${this.state.message} ${restarting}`;
		this.log.append(
			`${new Date().toISOString()} Restarting the detector in ${wait / 1000} seconds.\n`
		);
		void this.enqueue(async () => {
			try {
				await delay(wait, undefined, { signal });
				await this.startChild(signal, true);
			} catch (error) {
				if (signal.aborted) {
					this.state.phase = 'stopped';
					this.state.message = 'Restart cancelled.';
				} else this.fail(error);
			}
		});
	}

	stop(
		disable = true,
		reason = disable ? 'Monitoring disabled' : 'Application shutdown'
	): Promise<void> {
		// A stop cancels both the active check and starts already waiting in the queue.
		this.startup.abort();
		this.startup = new AbortController();
		return this.enqueue(async () => {
			this.log.append(`${new Date().toISOString()} Stop requested: ${reason}\n`);
			if (disable) this.settings.enabled = false;
			try {
				if (disable) await setMonitoringEnabled(this.appPath, false);
			} finally {
				try {
					await this.stopChild();
				} finally {
					await this.log.flush();
				}
			}
		});
	}

	private async stopChild(): Promise<void> {
		const child = this.child;
		if (!child) return;
		this.stoppingChild = true;
		this.state.phase = 'stopping';
		this.state.message = 'Finishing detections and stopping…';
		child.stdin.end('stop\n');
		let timedOut = false;
		const timer = setTimeout(() => {
			timedOut = true;
			this.fail(
				new SetupError(
					'The detector did not finish shutting down within 30 seconds. It was forced to stop; the last detection may be incomplete.'
				)
			);
			child.kill('SIGKILL');
		}, 30000);
		try {
			const code = await this.finished;
			if (code !== 0 || timedOut) throw new SetupError(this.state.message);
		} finally {
			clearTimeout(timer);
		}
	}

	apply(): Promise<void> {
		const signal = this.startup.signal;
		return this.enqueue(async () => {
			await this.restartChild(signal, 'detector settings changed');
		});
	}

	private async restartChild(signal: AbortSignal, reason: string): Promise<void> {
		if (!this.settings.enabled || signal.aborted) return;
		this.log.append(`${new Date().toISOString()} Restart requested: ${reason}\n`);
		try {
			await this.stopChild();
		} catch (error) {
			this.fail(error);
		}
		await this.startChild(signal, true);
	}

	fail(error: unknown): void {
		this.state.phase = 'failed';
		this.state.message =
			error instanceof Error ? redact(error.message) : 'The detector could not start.';
		this.state.helpUrl = error instanceof SetupError ? error.helpUrl : undefined;
		this.log.append(`${new Date().toISOString()} ERROR ${this.state.message}\n`);
		void this.log.flush();
	}
}

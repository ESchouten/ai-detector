import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import path from 'node:path';
import { createInterface } from 'node:readline';
import { setTimeout as delay } from 'node:timers/promises';
import type { RuntimeMode, RuntimeStatus } from '../runtime.ts';
import type { AppConfig, Config, LlmConnection } from '../schema.ts';
import { readJson, writeJson } from './json-file.ts';
import { DetectorLog } from './detector-log.ts';
import type { DetectorCommand } from './nvidia-runtime.ts';
import { DetectorPreparation, type DetectorOptions } from './detector-preparation.ts';
import { sanitizeTextForLogs as redact } from './runtime-logs.ts';
import { RuntimeProgress, STATUS_PREFIX } from './runtime-status.ts';
import { chooseRuntime, SetupError } from './runtime-platform.ts';

interface Settings {
	mode: RuntimeMode;
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
	private operation: Promise<unknown> = Promise.resolve();
	private startup = new AbortController();
	private restartDelay = INITIAL_RESTART_DELAY_MS;
	private settings: Settings = { mode: 'auto', enabled: false };
	private state: RuntimeStatus;
	private readonly settingsPath: string;
	private readonly preparation: DetectorPreparation;
	private readonly options: DetectorOptions;
	private progress = new RuntimeProgress();

	constructor(options: DetectorOptions) {
		this.options = options;
		this.log = new DetectorLog(options.dataDirectory);
		this.settingsPath = path.join(options.dataDirectory, 'runtime.json');
		this.preparation = new DetectorPreparation(options, this.log, (message) => {
			this.state.message = message;
		});
		this.state = {
			managed: true,
			mode: 'auto',
			selected: null,
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
			preparation: readiness === 'preparing' ? this.progress.preparation : undefined,
			notice: this.progress.notice,
			issues: this.progress.issues,
			backends: this.progress.backends,
			identification: this.progress.identification
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
			if (this.settings.enabled) {
				await this.log.resume();
				await this.startChild(this.settings.mode, signal, true);
			}
		});
	}

	validate(config: unknown, signal?: AbortSignal): Promise<void> {
		return this.preparation.validate(config, signal);
	}
	testLlm(connection: LlmConnection, signal?: AbortSignal): Promise<void> {
		return this.preparation.testLlm(connection, signal);
	}

	start(mode: RuntimeMode): Promise<void> {
		const signal = this.startup.signal;
		return this.enqueue(() => {
			if (!this.child) this.restartDelay = INITIAL_RESTART_DELAY_MS;
			return this.startChild(mode, signal);
		});
	}

	setMode(mode: RuntimeMode, previous: string): Promise<void> {
		return this.enqueue(async () => {
			if (this.state.mode !== previous)
				throw new SetupError('The detection engine changed. Reload the saved settings.');
			if (this.child || ['checking', 'starting', 'stopping'].includes(this.state.phase))
				throw new SetupError('Pause monitoring before changing the detection engine.');
			const settings = { ...this.settings, mode };
			await writeJson(this.settingsPath, settings);
			this.settings = settings;
			this.state.mode = mode;
		});
	}

	whileStopped<T>(operation: () => Promise<T>): Promise<T> {
		return this.enqueue(() => {
			if (this.settings.enabled || this.child)
				throw new SetupError('Pause monitoring before clearing the model cache.');
			return operation();
		});
	}

	private async startChild(
		mode: RuntimeMode,
		signal: AbortSignal,
		preserveLog = false
	): Promise<void> {
		if (this.child || signal.aborted) return;
		if (!preserveLog) this.log.begin();
		this.progress = new RuntimeProgress();
		this.state = {
			...this.state,
			phase: 'checking',
			mode,
			selected: null,
			helpUrl: undefined,
			message: 'Checking this computer…'
		};
		try {
			const config = await readJson<Config>(path.join(this.options.dataDirectory, 'config.json'));
			if (!config) throw new SetupError('Add a camera and choose what to detect first.');
			await this.validate(config, signal);
			const app = await readJson<AppConfig>(path.join(this.options.dataDirectory, 'app.json'));
			this.progress.configure(
				config,
				app ?? { streams: [], telegrams: [], llms: [], detectors: [] },
				this.options.dataDirectory
			);
			const selected = chooseRuntime(mode);
			this.state.selected = selected;
			this.log.append(`${new Date().toISOString()} Selected detection engine: ${selected}\n`);
			signal.throwIfAborted();
			const command = await this.preparation.command(selected, config, signal);
			signal.throwIfAborted();
			this.settings = { mode, enabled: true };
			await writeJson(this.settingsPath, this.settings);
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
					await this.restartChild(signal, `${stalled} stopped processing fresh camera frames`);
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
					await this.restartChild(signal, 'TensorRT models are ready');
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
		this.state.message += ` Restarting monitoring in ${wait / 1000} seconds…`;
		this.log.append(
			`${new Date().toISOString()} Restarting the detector in ${wait / 1000} seconds.\n`
		);
		void this.enqueue(async () => {
			try {
				await delay(wait, undefined, { signal });
				await this.startChild(this.settings.mode, signal, true);
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
				if (disable) await writeJson(this.settingsPath, this.settings);
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
				forcedStop = this.preparation
					.stopContainer()
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
		return this.enqueue(() => this.restartChild(signal, 'detector settings changed'));
	}

	private async restartChild(signal: AbortSignal, reason: string): Promise<void> {
		if (!this.settings.enabled || signal.aborted) return;
		this.log.append(`${new Date().toISOString()} Restart requested: ${reason}\n`);
		try {
			await this.stopChild();
		} catch (error) {
			this.fail(error);
		}
		await this.startChild(this.settings.mode, signal, true);
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

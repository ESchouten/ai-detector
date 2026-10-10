import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { existsSync } from 'node:fs';
import { mkdir, rm } from 'node:fs/promises';
import path from 'node:path';
import { createInterface } from 'node:readline';
import type { Config, LlmConnection } from '../schema.ts';
import { writeJson } from './json-file.ts';
import type { DetectorLog } from './detector-log.ts';
import {
	discoverNvidia,
	needsNvidiaRuntime,
	prepareNvidiaRuntime,
	type DetectorCommand
} from './nvidia-runtime.ts';
import { sanitizeTextForLogs as redact } from './runtime-logs.ts';
import { SetupError } from './runtime-platform.ts';

export interface DetectorOptions {
	executable: string;
	dataDirectory: string;
}

/** Temporary configuration checks and runtime dependencies, before process supervision begins. */
export class DetectorPreparation {
	private options: DetectorOptions;
	private log: DetectorLog;
	private report: (message: string) => void;
	constructor(options: DetectorOptions, log: DetectorLog, report: (message: string) => void) {
		this.options = options;
		this.log = log;
		this.report = report;
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

	async testLlm(connection: LlmConnection, signal?: AbortSignal): Promise<void> {
		const file = path.join(this.options.dataDirectory, `vlm-check-${randomUUID()}.json`);
		const { model, key, url, headers } = connection;
		try {
			await writeJson(file, {
				model,
				key,
				url,
				headers,
				prompt: /* @wc-ignore */ 'Connection test',
				strategy: 'IMAGE'
			});
			await this.runCheck(this.options.executable, ['--test-vlm', file], 45000, signal);
		} finally {
			await rm(file, { force: true });
		}
	}

	async command(config: Config, signal: AbortSignal): Promise<DetectorCommand> {
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

	private async nativeCommand(config: Config, signal: AbortSignal): Promise<DetectorCommand> {
		const bundleDirectory = path.join(path.dirname(this.options.executable), 'nvidia-runtime');
		if (needsNvidiaRuntime(config, process.platform) && existsSync(bundleDirectory)) {
			const device = await discoverNvidia(signal);
			if (device) {
				this.log.append(
					`Selected NVIDIA acceleration on ${device.name}; CUDA with optional direct TensorRT\n`
				);
				try {
					return await prepareNvidiaRuntime({
						bundleDirectory,
						dataDirectory: this.options.dataDirectory,
						device,
						signal,
						run: (file, args, timeout, env) => this.runCheck(file, args, timeout, signal, env),
						report: (message) => {
							this.report(message);
							this.log.append(`${new Date().toISOString()} ${message}\n`);
						}
					});
				} catch (error) {
					signal.throwIfAborted();
					if (error instanceof SetupError && error.helpUrl) throw error;
					this.log.append(`\nNVIDIA preparation failed: ${String(error)}\n`);
					throw new SetupError(
						'NVIDIA acceleration could not be prepared. Check your internet connection and graphics driver, then try again. Details are available below.'
					);
				}
			}
		}
		return { file: this.options.executable, args: [] };
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
			for (const input of [child.stdout, child.stderr]) {
				createInterface({ input, crlfDelay: Infinity }).on('line', (line) => {
					this.log.append(line + '\n');
					output = (output + line + '\n').slice(-4000);
				});
			}
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
}

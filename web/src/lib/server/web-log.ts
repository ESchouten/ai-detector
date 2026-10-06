import path from 'node:path';
import { BoundedLog } from './bounded-log.ts';
import { sanitizeTextForLogs } from './runtime-logs.ts';

/**
 * What the web application did and what went wrong, kept for diagnostics. An exception is
 * written as its kind, code and place, never its message: that can quote the input that failed,
 * a settings file with keys in it for one. Callers add what is safe to say.
 */
class WebLog {
	private output?: BoundedLog;

	async initialize(directory: string, version: string): Promise<void> {
		this.output = new BoundedLog(path.join(directory, 'logs', 'web.log'));
		try {
			await this.output.restore();
		} catch (error) {
			this.warn(/* @wc-ignore */ 'Could not read the previous web log', error);
		}
		this.output.append(`${new Date().toISOString()} Web application ${version} started\n`);
	}

	/** Something worth knowing afterwards that is not a problem by itself. */
	info(message: string): void {
		this.output?.append(`${new Date().toISOString()} INFO ${sanitizeTextForLogs(message)}\n`);
	}

	warn(message: string, error?: unknown): void {
		this.write('warn', message, error);
	}

	error(message: string, error: unknown): void {
		this.write('error', message, error);
	}

	private write(level: 'warn' | 'error', message: string, error: unknown): void {
		const details =
			error instanceof Error
				? [
						error.name,
						(error as NodeJS.ErrnoException).code,
						...(error.stack?.split('\n').filter((line) => /^\s+at /.test(line)) ?? [])
					]
						.filter(Boolean)
						.join('\n')
				: '';
		const text = sanitizeTextForLogs(`${message}${details ? `\n${details}` : ''}`);
		console[level](text);
		this.output?.append(`${new Date().toISOString()} ${level.toUpperCase()} ${text}\n`);
	}

	async flush(): Promise<void> {
		await this.output?.flush();
	}

	async read(): Promise<string> {
		return this.output ? this.output.read() : '';
	}
}

export const webLog = new WebLog();

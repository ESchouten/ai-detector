import path from 'node:path';
import { BoundedLog } from './bounded-log.ts';
import { sanitizeTextForLogs } from './runtime-logs.ts';

/** Persist operational failures without serializing exception inputs or credentials. */
class WebLog {
	private output?: BoundedLog;

	async initialize(directory: string): Promise<void> {
		this.output = new BoundedLog(path.join(directory, 'logs', 'web.log'));
		try {
			await this.output.restore();
		} catch (error) {
			this.warn('Could not read the previous web log', error);
		}
		this.output.append(`${new Date().toISOString()} Web application started\n`);
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

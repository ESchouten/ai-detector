import { mkdir, open } from 'node:fs/promises';
import path from 'node:path';
import { stripVTControlCharacters } from 'node:util';
import writeFileAtomic from 'write-file-atomic';
import { isMissingFile } from './json-file.ts';

function sanitizeParameters(text: string): string {
	return text.replace(
		/((?:^|[?&;/])(?:user(?:name)?|pass(?:word)?|pwd|token|key|api_key)=)([^&;\s]+)/gi,
		'$1***'
	);
}

export function sanitizeSourceForLogs(source: string): string {
	const sanitized = sanitizeParameters(source);

	try {
		const url = new URL(sanitized);
		url.username = url.username ? '***' : '';
		url.password = url.password ? '***' : '';
		return url.toString();
	} catch {
		return sanitized;
	}
}

export function sanitizeTextForLogs(text: string): string {
	return sanitizeParameters(text)
		.replace(/(pairing code:\s*)\d{6}/gi, '$1***')
		.replace(/\bbot\d+:[A-Za-z0-9_-]+/g, 'bot***')
		.replace(/\b[a-z][a-z0-9+.-]*:\/\/[^\s\r\n]+/gi, (source) => sanitizeSourceForLogs(source));
}

const START_LIMIT = 32 * 1024;
const RECENT_LIMIT = 96 * 1024;
const OMITTED = '\n\n[Earlier activity omitted; startup and latest output are retained.]\n\n';

/** One bounded transcript: keep startup even when inference produces many lines. */
export class BoundedLog {
	private start = '';
	private recent = '';
	private truncated = false;
	private timer: ReturnType<typeof setTimeout> | undefined;
	private pending: Promise<void> = Promise.resolve();
	private readonly file: string;

	constructor(file: string) {
		this.file = file;
	}

	async restore(): Promise<void> {
		if (!this.start) this.append(await readLogTail(this.file));
	}

	clear(): void {
		this.start = '';
		this.recent = '';
		this.truncated = false;
	}

	append(text: string): void {
		const clean = sanitizeTextForLogs(stripVTControlCharacters(text));
		const remaining = START_LIMIT - this.start.length;
		this.start += clean.slice(0, remaining);
		this.recent += clean.slice(remaining);
		if (this.recent.length > RECENT_LIMIT) {
			this.recent = this.recent.slice(-RECENT_LIMIT);
			this.recent = this.recent.slice(this.recent.indexOf('\n') + 1);
			this.truncated = true;
		}
		this.timer ??= setTimeout(() => void this.flush(), 1000);
	}

	async read(): Promise<string> {
		return this.start ? this.snapshot() : readLogTail(this.file);
	}

	private snapshot(): string {
		return this.start + (this.truncated ? OMITTED : '') + this.recent;
	}

	flush(): Promise<void> {
		clearTimeout(this.timer);
		this.timer = undefined;
		if (!this.start) return this.pending;
		const text = this.snapshot();
		this.pending = this.pending
			.then(async () => {
				await mkdir(path.dirname(this.file), { recursive: true });
				await writeFileAtomic(this.file, text, { mode: 0o600, fsync: false });
			})
			.catch((error: NodeJS.ErrnoException) => {
				console.error(`Could not save ${path.basename(this.file)}:`, error.code);
			});
		return this.pending;
	}
}

/** Also supports the existing Python log for separately managed installations. */
export async function readLogTail(file: string): Promise<string> {
	let handle;
	try {
		handle = await open(file, 'r');
	} catch (error) {
		if (isMissingFile(error)) return '';
		throw error;
	}
	try {
		const { size } = await handle.stat();
		const buffer = Buffer.alloc(Math.min(size, 512 * 1024));
		const { bytesRead } = await handle.read(buffer, 0, buffer.length, size - buffer.length);
		return sanitizeTextForLogs(stripVTControlCharacters(buffer.subarray(0, bytesRead).toString()));
	} finally {
		await handle.close();
	}
}

/** The transcript of the current monitoring attempt. */
export class DetectorLog extends BoundedLog {
	constructor(directory: string) {
		super(path.join(directory, 'logs', 'application.log'));
	}

	async resume(): Promise<void> {
		await this.restore();
		this.append(`${new Date().toISOString()} Resuming monitoring after application startup\n`);
	}

	begin(): void {
		this.clear();
		this.append(`${new Date().toISOString()} Starting monitoring\n`);
	}
}

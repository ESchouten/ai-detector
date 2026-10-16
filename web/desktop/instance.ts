/** Local launcher identity; never trust an arbitrary process occupying the dashboard port. */
import { createHmac, randomBytes, timingSafeEqual } from 'node:crypto';
import { mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';

export const CONTROL_PATH = '/.well-known/ai-detector-instance';
const PROTOCOL = 'ai-detector-desktop/1';
type SavedInstance = { port: number; token: string; pid: number };

function proof(token: string, action: string, challenge: string): string {
	return createHmac('sha256', token).update(`${PROTOCOL}:${action}:${challenge}`).digest('hex');
}

function matches(actual: string, expected: string): boolean {
	const left = Buffer.from(actual);
	const right = Buffer.from(expected);
	return left.length === right.length && timingSafeEqual(left, right);
}

export class DesktopInstance {
	private token = randomBytes(32).toString('hex');
	private file: string;
	private shutdownFile: string;
	private portFile: string;
	private connected?: SavedInstance;

	constructor(directory: string) {
		mkdirSync(directory, { recursive: true, mode: 0o700 });
		this.file = path.join(directory, 'desktop-instance.json');
		this.shutdownFile = path.join(directory, 'desktop-shutdown.json');
		this.portFile = path.join(directory, 'desktop-port.json');
	}

	/** Publish only after successfully binding the server; the OS port is the instance lock. */
	publish(port: number): void {
		writePrivate(this.file, { port, token: this.token, pid: process.pid });
	}

	/** The port the dashboard moved to when its usual one was taken. */
	savedPort(): number | undefined {
		try {
			return JSON.parse(readFileSync(this.portFile, 'utf8')).port;
		} catch (error) {
			if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
		}
	}

	savePort(port: number): void {
		writePrivate(this.portFile, { port });
	}

	/** A copy that published this port and still runs, even while it is too busy starting to answer. */
	running(port: number): boolean {
		try {
			const saved = this.readRecord(port);
			if (saved) process.kill(saved.pid, 0);
			return Boolean(saved);
		} catch (error) {
			// No record, or its process has ended; EPERM is a process that exists.
			return !['ENOENT', 'ESRCH'].includes((error as NodeJS.ErrnoException).code ?? '');
		}
	}

	/** A reattached menu must distinguish a completed Quit from a vanished/crashed owner. */
	completeShutdown(success: boolean): void {
		writePrivate(this.shutdownFile, { token: this.token, success });
	}

	shutdownResult(): boolean | undefined {
		try {
			const saved = JSON.parse(readFileSync(this.shutdownFile, 'utf8'));
			if (saved.token === this.connected?.token) return saved.success;
		} catch (error) {
			if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
		}
	}

	/** Called only after authenticating the port owner; an HTTP stall is not a process crash. */
	async waitForShutdown(signal: AbortSignal): Promise<boolean | undefined> {
		await waitForExit(this.connected!.pid, Infinity, signal);
		return this.shutdownResult();
	}

	private async awaitShutdown(saved: SavedInstance, acknowledged = false): Promise<boolean> {
		if (!(await waitForExit(saved.pid, 45000))) return false;
		const result = this.shutdownResult();
		return acknowledged ? result === true : result !== false;
	}

	remove(): void {
		try {
			if (JSON.parse(readFileSync(this.file, 'utf8')).token === this.token) rmSync(this.file);
		} catch (error) {
			if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
		}
	}

	respond(request: Request, quit: () => void): Response | undefined {
		if (new URL(request.url).pathname !== CONTROL_PATH) return;
		const challenge = request.headers.get('X-AI-Detector-Challenge') ?? '';
		if (!/^[a-f0-9]{64}$/.test(challenge)) return new Response(null, { status: 400 });
		if (request.method === 'POST') {
			if (
				!matches(request.headers.get('Authorization') ?? '', proof(this.token, 'quit', challenge))
			)
				return new Response(null, { status: 403 });
			setTimeout(quit, 0);
		} else if (request.method !== 'GET') return new Response(null, { status: 405 });
		return Response.json(
			{ protocol: PROTOCOL, proof: proof(this.token, 'open', challenge) },
			{
				headers: { 'Cache-Control': 'no-store' }
			}
		);
	}

	/** Retry the short bind-to-publication race; a wrong signature never opens a browser. */
	async existing(port: number, quit = false, timeout = 5000): Promise<boolean> {
		const deadline = Date.now() + timeout;
		do {
			let saved: SavedInstance | undefined;
			try {
				saved = this.readRecord(port);
				if (!saved) return false;
				this.connected = saved;
				if (await probe(saved, quit, deadline))
					return quit ? this.awaitShutdown(saved, true) : true;
			} catch (error) {
				const failure = error as NodeJS.ErrnoException & { cause?: NodeJS.ErrnoException };
				if (quit && failure.code === 'ENOENT') return true;
				if (quit && saved && connectionRefused(failure)) return this.awaitShutdown(saved);
				// A stale record or a server still starting cannot authorize a browser launch.
			}
			await delay(100);
		} while (Date.now() < deadline);
		return false;
	}

	private readRecord(port: number): SavedInstance | undefined {
		const saved: SavedInstance = JSON.parse(readFileSync(this.file, 'utf8'));
		if (saved.port === port) return saved;
	}
}

function writePrivate(file: string, record: object): void {
	const temporary = `${file}.${process.pid}.tmp`;
	writeFileSync(temporary, JSON.stringify(record), { mode: 0o600 });
	renameSync(temporary, file);
}

async function probe(saved: SavedInstance, quit: boolean, deadline: number): Promise<boolean> {
	const challenge = randomBytes(32).toString('hex');
	const response = await fetch(`http://127.0.0.1:${saved.port}${CONTROL_PATH}`, {
		method: quit ? 'POST' : 'GET',
		headers: {
			'X-AI-Detector-Challenge': challenge,
			...(quit ? { Authorization: proof(saved.token, 'quit', challenge) } : {})
		},
		signal: AbortSignal.timeout(Math.max(1, Math.min(1000, deadline - Date.now()))),
		redirect: 'error'
	});
	if (!response.ok) return false;
	const result = await response.json();
	return (
		result.protocol === PROTOCOL &&
		matches(result.proof ?? '', proof(saved.token, 'open', challenge))
	);
}

async function waitForExit(pid: number, timeout: number, signal?: AbortSignal): Promise<boolean> {
	const deadline = Date.now() + timeout;
	do {
		try {
			process.kill(pid, 0);
		} catch (error) {
			if ((error as NodeJS.ErrnoException).code === 'ESRCH') return true;
			throw error;
		}
		await delay(100, undefined, { signal });
	} while (Date.now() < deadline);
	return false;
}

// Node wraps socket failures in cause; Bun supplies its own connection error code.
function connectionRefused(
	error: NodeJS.ErrnoException & { cause?: NodeJS.ErrnoException }
): boolean {
	return ['ECONNREFUSED', 'ConnectionRefused'].includes(error.cause?.code ?? error.code ?? '');
}

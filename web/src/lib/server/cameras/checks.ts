import { execFile } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdir, readdir, rm, stat } from 'node:fs/promises';
import path from 'node:path';
import { promisify } from 'node:util';
import type { CameraConnectionResult, CameraProfile } from '../../cameras.ts';
import { getCameraInputArgs } from '../ffmpeg.ts';
import { CameraConnectionError, cameraStorageFailure, connectionFailure } from './connection.ts';

const execute = promisify(execFile);
const LIFETIME_MS = 15 * 60 * 1000;
const MAX_CHECKS = 16;
type Check = { source: string; checkedAt: number; directory: string };

export async function recordCameraTest(
	source: string,
	executable: string,
	directory: string,
	signal?: AbortSignal
): Promise<void> {
	try {
		await execute(
			executable,
			[
				'-hide_banner',
				'-loglevel',
				'error',
				'-nostdin',
				'-y',
				...getCameraInputArgs(source),
				'-map',
				'0:v:0',
				'-an',
				'-t',
				'2',
				'-vf',
				'fps=12,scale=640:-2',
				'-c:v',
				'libx264',
				'-preset',
				'ultrafast',
				'-pix_fmt',
				'yuv420p',
				'-movflags',
				'+faststart',
				'-fs',
				'10485760',
				path.join(directory, 'recording.mp4')
			],
			{ timeout: 25000, killSignal: 'SIGKILL', maxBuffer: 64 * 1024, windowsHide: true, signal }
		);
		// Decode the recorded result too: a successful camera connection alone is not enough.
		await execute(
			executable,
			[
				'-hide_banner',
				'-loglevel',
				'error',
				'-nostdin',
				'-y',
				'-i',
				path.join(directory, 'recording.mp4'),
				'-frames:v',
				'1',
				path.join(directory, 'picture.jpg')
			],
			{ timeout: 5000, killSignal: 'SIGKILL', maxBuffer: 64 * 1024, windowsHide: true, signal }
		);
	} catch (cause) {
		signal?.throwIfAborted();
		const failure = cause as NodeJS.ErrnoException & { stderr?: string; killed?: boolean };
		if (failure.code === 'ENOENT')
			throw new CameraConnectionError(
				'The camera software is missing. Repair or reinstall AI Detector and try again.'
			);
		if (failure.killed)
			throw new CameraConnectionError(
				'The camera check took too long. Try again or choose another camera channel.'
			);
		// execFile's message includes the command and credentials. Only actual diagnostics classify the failure.
		throw connectionFailure(failure.stderr || failure.code || 'Camera check failed');
	}
}

/** Short-lived setup recordings, isolated from real detections and addressed without credentials. */
export class CameraChecks {
	private readonly checks = new Map<string, Check>();
	private active = false;
	private readonly directory: string;
	private readonly now: () => number;
	constructor(directory: string, now: () => number = Date.now) {
		this.directory = directory;
		this.now = now;
	}

	async check(
		source: string,
		executable: string,
		profiles: CameraProfile[],
		signal?: AbortSignal
	): Promise<CameraConnectionResult> {
		if (this.active)
			throw new CameraConnectionError(
				'Another camera check is still running. Please wait a moment and try again.'
			);
		this.active = true;
		const id = randomUUID();
		const directory = path.join(this.directory, id);
		try {
			await this.prune();
			await mkdir(directory, { recursive: true, mode: 0o700 });
			await recordCameraTest(source, executable, directory, signal);
			const checkedAt = this.now();
			this.checks.set(id, { source, checkedAt, directory });
			return {
				source,
				checkId: id,
				checkedAt: new Date(checkedAt).toISOString(),
				profiles,
				previewUrl: `/camera-checks/${id}/picture.jpg`,
				recordingUrl: `/camera-checks/${id}/recording.mp4`
			};
		} catch (cause) {
			try {
				await rm(directory, { recursive: true, force: true });
			} catch (cleanupError) {
				console.warn(
					'Could not remove an incomplete camera check:',
					(cleanupError as NodeJS.ErrnoException).code
				);
			}
			throw cameraStorageFailure(cause) ?? cause;
		} finally {
			this.active = false;
		}
	}

	assert(id: string | undefined, source: string): string {
		const check = id ? this.checks.get(id) : undefined;
		if (!check || check.source !== source || this.now() - check.checkedAt >= LIFETIME_MS)
			throw new CameraConnectionError(
				'Check the camera picture again before saving. The previous check has expired or the camera address changed.'
			);
		return new Date(check.checkedAt).toISOString();
	}

	file(id: string, resource: string): string | null {
		const check = this.checks.get(id);
		if (!check || this.now() - check.checkedAt >= LIFETIME_MS) return null;
		return ['picture.jpg', 'recording.mp4'].includes(resource)
			? path.join(check.directory, resource)
			: null;
	}

	private async prune(): Promise<void> {
		await mkdir(this.directory, { recursive: true, mode: 0o700 });
		const cutoff = this.now() - LIFETIME_MS;
		for (const [id, check] of this.checks) {
			if (check.checkedAt <= cutoff || this.checks.size >= MAX_CHECKS) {
				await rm(check.directory, { recursive: true, force: true });
				this.checks.delete(id);
			}
		}
		// Also clean expired recordings left by an earlier application session.
		for (const entry of await readdir(this.directory, { withFileTypes: true })) {
			if (
				!entry.isDirectory() ||
				!/^[0-9a-f-]{36}$/.test(entry.name) ||
				this.checks.has(entry.name)
			)
				continue;
			const directory = path.join(this.directory, entry.name);
			if ((await stat(directory)).mtimeMs <= cutoff)
				await rm(directory, { recursive: true, force: true });
		}
	}
}

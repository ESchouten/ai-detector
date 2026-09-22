import { spawn } from 'node:child_process';
import { Readable } from 'node:stream';
import { getCameraInputArgs, sanitizeSourceForLogs, sanitizeTextForLogs } from './ffmpeg.ts';

export const MJPEG_BOUNDARY = 'frame';
const FIRST_FRAME_TIMEOUT_MS = 20_000;
const NO_FRAME_TIMEOUT_MS = 8_000;
const FORCE_KILL_DELAY_MS = 2_000;

/** Own one preview process until it exits, including when the response is cancelled. */
export function createPreviewStream(source: string, executable: string, signal: AbortSignal) {
	if (signal.aborted)
		return new ReadableStream<Uint8Array>({
			start(controller) {
				controller.close();
			}
		});
	const child = spawn(
		executable,
		[
			'-hide_banner',
			'-loglevel',
			'error',
			'-nostdin',
			...getCameraInputArgs(source),
			'-map',
			'0:v:0',
			'-an',
			'-sn',
			'-dn',
			'-c:v',
			'mjpeg',
			'-vf',
			'fps=8,scale=960:-1:flags=lanczos',
			'-q:v',
			'7',
			'-f',
			'mpjpeg',
			'-boundary_tag',
			MJPEG_BOUNDARY,
			'pipe:1'
		],
		{ stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true }
	);
	// Bound queued preview data to 64 KiB independently of the runtime's stream defaults.
	const reader = (
		Readable.toWeb(child.stdout, {
			strategy: { highWaterMark: 64 * 1024, size: (chunk: Uint8Array) => chunk.byteLength }
		}) as ReadableStream<Uint8Array>
	).getReader();
	let controller: ReadableStreamDefaultController<Uint8Array>;
	let responseClosed = false;
	let stopping = false;
	let hadFrame = false;
	let stderr = '';
	let readTimer: ReturnType<typeof setTimeout> | undefined;
	let killTimer: ReturnType<typeof setTimeout> | undefined;

	child.stderr.on('data', (chunk: Buffer) => {
		stderr = (stderr + chunk.toString()).slice(-4000);
	});
	child.once('error', (error) => {
		console.warn('Could not start FFmpeg preview:', sanitizeTextForLogs(error.message));
	});
	const finished = new Promise<void>((resolve) =>
		child.once('close', (code) => {
			clearTimeout(readTimer);
			clearTimeout(killTimer);
			signal.removeEventListener('abort', onAbort);
			if (!stopping && code !== 0)
				console.warn('FFmpeg preview failed', {
					source: sanitizeSourceForLogs(source),
					code,
					stderr: sanitizeTextForLogs(stderr.trim())
				});
			resolve();
		})
	);

	function stop(): Promise<void> {
		if (!stopping) {
			stopping = true;
			clearTimeout(readTimer);
			child.stdout.destroy();
			if (child.exitCode === null && child.signalCode === null) {
				child.kill('SIGTERM');
				// Response completion must not clear this timer; only process closure does.
				killTimer = setTimeout(() => child.kill('SIGKILL'), FORCE_KILL_DELAY_MS);
			}
		}
		return finished;
	}

	function finish(error?: Error): void {
		if (responseClosed) return;
		responseClosed = true;
		if (error) controller.error(error);
		else controller.close();
	}

	function onAbort(): void {
		finish();
		void stop();
	}

	return new ReadableStream<Uint8Array>({
		start(value) {
			controller = value;
			if (signal.aborted) onAbort();
			else signal.addEventListener('abort', onAbort, { once: true });
		},
		async pull() {
			readTimer = setTimeout(
				() => {
					finish(
						new Error(
							hadFrame ? 'Live stream stopped receiving frames.' : 'Live stream unavailable.'
						)
					);
					void stop();
				},
				hadFrame ? NO_FRAME_TIMEOUT_MS : FIRST_FRAME_TIMEOUT_MS
			);
			try {
				const next = await reader.read();
				clearTimeout(readTimer);
				if (responseClosed) return;
				if (next.done) {
					finish(new Error(hadFrame ? 'Live stream ended.' : 'Live stream unavailable.'));
					await stop();
				} else {
					hadFrame = true;
					controller.enqueue(next.value);
				}
			} catch {
				finish(new Error('Live stream unavailable.'));
				await stop();
			}
		},
		cancel() {
			responseClosed = true;
			return stop();
		}
	});
}

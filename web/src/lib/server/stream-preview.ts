import { spawn } from 'node:child_process';
import { MultipartParser, type MultipartPart } from '@remix-run/multipart-parser';
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
	// Always drain FFmpeg. Browser backpressure must drop pictures, not delay camera capture.
	const parser = new MultipartParser(MJPEG_BOUNDARY, {
		maxFileSize: 8 * 1024 * 1024,
		maxParts: Infinity,
		maxTotalSize: Infinity
	});
	let latest: MultipartPart | undefined;
	let waiting = false;
	let controller: ReadableStreamDefaultController<Uint8Array>;
	let responseClosed = false;
	let stopping = false;
	let hadFrame = false;
	let stderr = '';
	let readTimer: ReturnType<typeof setTimeout> | undefined;
	let killTimer: ReturnType<typeof setTimeout> | undefined;

	child.stdout.on('data', (chunk: Buffer) => {
		if (responseClosed) return;
		try {
			for (const part of parser.write(chunk)) {
				hadFrame = true;
				latest = part;
				armReadTimeout(NO_FRAME_TIMEOUT_MS);
				sendLatest();
			}
		} catch {
			finish(new Error('Invalid live picture received.'));
			void stop();
		}
	});
	child.stdout.once('end', () => {
		finish(new Error(hadFrame ? 'Live stream ended.' : 'Live stream unavailable.'));
		void stop();
	});
	child.stdout.once('error', () => {
		finish(new Error('Live stream unavailable.'));
		void stop();
	});
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
		latest = undefined;
		if (error) controller.error(error);
		else controller.close();
	}

	function onAbort(): void {
		finish();
		void stop();
	}

	function armReadTimeout(delay: number): void {
		clearTimeout(readTimer);
		readTimer = setTimeout(() => {
			finish(
				new Error(hadFrame ? 'Live stream stopped receiving frames.' : 'Live stream unavailable.')
			);
			void stop();
		}, delay);
	}

	function sendLatest(): void {
		if (!waiting || !latest || responseClosed) return;
		const picture = latest.bytes;
		latest = undefined;
		waiting = false;
		controller.enqueue(
			Buffer.concat([
				Buffer.from(
					`--${MJPEG_BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: ${picture.byteLength}\r\n\r\n`
				),
				picture,
				Buffer.from('\r\n')
			])
		);
	}

	return new ReadableStream<Uint8Array>(
		{
			start(value) {
				controller = value;
				armReadTimeout(FIRST_FRAME_TIMEOUT_MS);
				if (signal.aborted) onAbort();
				else signal.addEventListener('abort', onAbort, { once: true });
			},
			pull() {
				waiting = true;
				sendLatest();
			},
			cancel() {
				responseClosed = true;
				latest = undefined;
				return stop();
			}
		},
		{ highWaterMark: 0 }
	);
}

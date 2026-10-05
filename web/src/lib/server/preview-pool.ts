import { createPreviewStream } from './stream-preview.ts';

interface Viewer {
	controller: ReadableStreamDefaultController<Uint8Array>;
	latest?: Uint8Array;
	waiting: boolean;
	close(error?: unknown): void;
}

interface Preview {
	viewers: Set<Viewer>;
	reader: ReadableStreamDefaultReader<Uint8Array>;
	/** Ends the capture when nobody came back for it. */
	idle?: ReturnType<typeof setTimeout>;
}

/**
 * Share capture/encoding; each browser retains only its latest undelivered picture. A capture
 * stays for a while after its last viewer left: a camera only shows a picture from its next
 * keyframe, which takes seconds, so someone who scrolls back or opens the camera sees it at once.
 */
export class PreviewPool {
	private previews = new Map<string, Preview>();
	private readonly lingerMs: number;

	constructor(lingerMs = 20_000) {
		this.lingerMs = lingerMs;
	}

	open(source: string, executable: string, signal: AbortSignal): ReadableStream<Uint8Array> {
		if (signal.aborted) return new ReadableStream({ start: (controller) => controller.close() });
		const key = JSON.stringify([source, executable]);
		let preview = this.previews.get(key);
		if (!preview) {
			preview = {
				viewers: new Set(),
				reader: createPreviewStream(source, executable, new AbortController().signal).getReader()
			};
			this.previews.set(key, preview);
			void this.broadcast(key, preview);
		}
		const shared = preview;
		clearTimeout(shared.idle);
		let viewer: Viewer;
		const detach = () => {
			signal.removeEventListener('abort', abort);
			shared.viewers.delete(viewer);
			viewer.latest = undefined;
			if (shared.viewers.size || this.previews.get(key) !== shared) return;
			shared.idle = setTimeout(() => {
				if (this.previews.get(key) === shared) this.previews.delete(key);
				void shared.reader.cancel().catch(() => undefined);
			}, this.lingerMs);
			shared.idle.unref();
		};
		const abort = () => viewer.close();
		let closed = false;
		return new ReadableStream<Uint8Array>(
			{
				start(controller) {
					viewer = {
						controller,
						waiting: false,
						close(error) {
							if (closed) return;
							closed = true;
							if (error) controller.error(error);
							else controller.close();
							void detach();
						}
					};
					shared.viewers.add(viewer);
					signal.addEventListener('abort', abort, { once: true });
				},
				pull() {
					viewer.waiting = true;
					sendLatest(viewer);
				},
				cancel() {
					closed = true;
					return detach();
				}
			},
			{ highWaterMark: 0 }
		);
	}

	private async broadcast(key: string, preview: Preview): Promise<void> {
		try {
			while (true) {
				const { value, done } = await preview.reader.read();
				if (done) break;
				for (const viewer of preview.viewers) {
					viewer.latest = value;
					sendLatest(viewer);
				}
			}
			for (const viewer of preview.viewers) viewer.close();
		} catch (error) {
			for (const viewer of preview.viewers) viewer.close(error);
		} finally {
			clearTimeout(preview.idle);
			if (this.previews.get(key) === preview) this.previews.delete(key);
			preview.reader.releaseLock();
		}
	}

	async close(): Promise<void> {
		const active = Array.from(this.previews.values());
		this.previews.clear();
		await Promise.all(
			active.map(async (preview) => {
				clearTimeout(preview.idle);
				for (const viewer of preview.viewers) viewer.close();
				await preview.reader.cancel().catch(() => undefined);
			})
		);
	}
}

function sendLatest(viewer: Viewer): void {
	if (!viewer.waiting || !viewer.latest) return;
	viewer.controller.enqueue(viewer.latest);
	viewer.latest = undefined;
	viewer.waiting = false;
}

export const previews = new PreviewPool();

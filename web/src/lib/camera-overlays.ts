import type { CameraOverlayFrame, LivePreviewStatus } from './live-preview.ts';

type Listener = (frames: CameraOverlayFrame[]) => void;
type Connection = Pick<EventTarget, 'addEventListener'> & { close(): void };

/** One metadata connection per page; camera video stays independent of inference. */
export class CameraOverlays {
	private viewers = new Map<string, Set<Listener>>();
	private frames = new Map<string, Map<string, CameraOverlayFrame>>();
	private connection?: Connection;
	private watchdog?: ReturnType<typeof setInterval>;
	private pending = false;
	private connectedIds = '';
	private endpoint: () => string;
	private connect: (url: string) => Connection;

	constructor(
		endpoint: () => string,
		connect: (url: string) => Connection = (url) => new EventSource(url)
	) {
		this.endpoint = endpoint;
		this.connect = connect;
	}

	subscribe(id: string, listener: Listener): () => void {
		const viewers = this.viewers.get(id) ?? new Set<Listener>();
		viewers.add(listener);
		this.viewers.set(id, viewers);
		listener([...(this.frames.get(id)?.values() ?? [])]);
		this.schedule();
		return () => {
			viewers.delete(listener);
			if (!viewers.size) {
				this.viewers.delete(id);
				this.frames.delete(id);
			}
			listener([]);
			this.schedule();
		};
	}

	private schedule() {
		if (this.pending) return;
		this.pending = true;
		queueMicrotask(() => {
			this.pending = false;
			this.reconnect();
		});
	}

	private notify(id: string) {
		const frames = [...(this.frames.get(id)?.values() ?? [])];
		for (const listener of this.viewers.get(id) ?? []) listener(frames);
	}

	private clear() {
		this.frames.clear();
		for (const id of this.viewers.keys()) this.notify(id);
	}

	private reconnect() {
		const ids = [...this.viewers.keys()].sort();
		const query = new URLSearchParams(ids.map((id) => ['camera', id])).toString();
		if (query === this.connectedIds) return;
		this.connectedIds = query;
		this.connection?.close();
		clearInterval(this.watchdog);
		this.clear();
		if (!ids.length) {
			this.connection = undefined;
			return;
		}
		const connection = this.connect(`${this.endpoint()}?${query}`);
		this.connection = connection;
		let lastContact = Date.now();
		const contact = () => {
			lastContact = Date.now();
		};
		connection.addEventListener('heartbeat', contact);
		connection.addEventListener('error', () => this.clear());
		connection.addEventListener('frame', (event) => {
			contact();
			const frame: CameraOverlayFrame = JSON.parse((event as MessageEvent<string>).data);
			if (!this.viewers.has(frame.cameraId)) return;
			const frames = this.frames.get(frame.cameraId) ?? new Map<string, CameraOverlayFrame>();
			frames.set(frame.ruleId, frame);
			this.frames.set(frame.cameraId, frames);
			this.notify(frame.cameraId);
		});
		connection.addEventListener('status', (event) => {
			contact();
			const status: LivePreviewStatus = JSON.parse((event as MessageEvent<string>).data);
			if (status.cameraId && status.ruleId) {
				this.frames.get(status.cameraId)?.delete(status.ruleId);
				this.notify(status.cameraId);
			} else this.clear();
		});
		this.watchdog = setInterval(() => {
			if (Date.now() - lastContact > 7000 && this.frames.size) this.clear();
		}, 1000);
	}
}

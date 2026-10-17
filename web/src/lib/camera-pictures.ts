import type { CameraOverlayFrame, LivePreviewStatus } from './live-preview.ts';

/**
 * Live pictures of several cameras travel over one connection: a browser allows about six
 * connections to an address without HTTPS, and a connection per camera used them up, which left
 * the rest of the page waiting.
 *
 * A record is the camera's id and one JPEG file, each preceded by its length. An empty picture
 * says that the camera's stream has ended.
 */
export function pictureRecord(id: string, picture: Uint8Array): Uint8Array {
	const name = new TextEncoder().encode(id);
	const record = new Uint8Array(1 + name.length + 4 + picture.length);
	record[0] = name.length;
	record.set(name, 1);
	new DataView(record.buffer).setUint32(1 + name.length, picture.length);
	record.set(picture, 5 + name.length);
	return record;
}

/** Collects what arrives and hands out each record once it is complete. */
export class PictureRecords {
	private pending = new Uint8Array(0);

	read(chunk: Uint8Array): { id: string; picture: Uint8Array }[] {
		const bytes = new Uint8Array(this.pending.length + chunk.length);
		bytes.set(this.pending);
		bytes.set(chunk, this.pending.length);
		const records = [];
		let start = 0;
		while (bytes.length - start >= 5 + bytes[start]) {
			const picture = start + 5 + bytes[start];
			const length = new DataView(bytes.buffer).getUint32(picture - 4);
			if (bytes.length < picture + length) break;
			records.push({
				id: new TextDecoder().decode(bytes.subarray(start + 1, picture - 4)),
				picture: bytes.slice(picture, picture + length)
			});
			start = picture + length;
		}
		this.pending = bytes.slice(start);
		return records;
	}
}

/**
 * The cameras a page shows, each with its viewers. `connect` runs once for every batch of
 * cameras that appear or leave together, with the cameras still shown and their query.
 */
class WatchedCameras<Listener> {
	private viewers = new Map<string, Set<Listener>>();
	private connected = '';
	private pending = false;
	private connect: (ids: string[], query: string) => void;

	constructor(connect: (ids: string[], query: string) => void) {
		this.connect = connect;
	}

	of(id: string): ReadonlySet<Listener> {
		return this.viewers.get(id) ?? new Set();
	}

	ids(): string[] {
		return [...this.viewers.keys()];
	}

	add(id: string, listener: Listener): void {
		const viewers = this.viewers.get(id) ?? new Set<Listener>();
		viewers.add(listener);
		this.viewers.set(id, viewers);
		this.schedule();
	}

	/** Whether this was the camera's last viewer. */
	remove(id: string, listener: Listener): boolean {
		const viewers = this.viewers.get(id);
		viewers?.delete(listener);
		const last = !viewers?.size;
		if (last) this.viewers.delete(id);
		this.schedule();
		return last;
	}

	/** The connection ended; the next change connects again, even to the same cameras. */
	disconnected(): void {
		this.connected = '';
	}

	private schedule() {
		if (this.pending) return;
		this.pending = true;
		queueMicrotask(() => {
			this.pending = false;
			const ids = this.ids().sort();
			const query = new URLSearchParams(ids.map((id) => ['camera', id])).toString();
			if (query === this.connected) return;
			this.connected = query;
			this.connect(ids, query);
		});
	}
}

/** What a viewer is told: the address of the newest picture, or that the stream has ended. */
type Listener = (picture: string | null) => void;
type Read = (url: string, signal: AbortSignal) => Promise<ReadableStream<Uint8Array>>;

async function readPictures(url: string, signal: AbortSignal) {
	const response = await fetch(url, { signal });
	if (!response.ok || !response.body)
		throw new Error(/* @wc-ignore */ 'Live pictures are unavailable.');
	return response.body;
}

/** One connection per page for the pictures of every camera that is being watched. */
export class CameraPictures {
	private cameras = new WatchedCameras<Listener>((ids, query) => this.reconnect(ids, query));
	private shown = new Map<string, string>();
	/** Cameras whose stream ended; asking for one again needs a new connection. */
	private ended = new Set<string>();
	private connection?: AbortController;
	private endpoint: () => string;
	private read: Read;

	constructor(endpoint: () => string, read: Read = readPictures) {
		this.endpoint = endpoint;
		this.read = read;
	}

	subscribe(id: string, listener: Listener): () => void {
		if (this.ended.delete(id)) this.cameras.disconnected();
		this.cameras.add(id, listener);
		const shown = this.shown.get(id);
		if (shown) listener(shown);
		return () => {
			if (this.cameras.remove(id, listener)) this.forget(id);
		};
	}

	private forget(id: string) {
		const shown = this.shown.get(id);
		if (shown) URL.revokeObjectURL(shown);
		this.shown.delete(id);
	}

	private show(id: string, picture: Uint8Array) {
		const viewers = this.cameras.of(id);
		if (!viewers.size) return;
		const previous = this.shown.get(id);
		const url = picture.length
			? URL.createObjectURL(new Blob([picture as BlobPart], { type: 'image/jpeg' }))
			: null;
		if (url) this.shown.set(id, url);
		else {
			this.shown.delete(id);
			this.ended.add(id);
		}
		for (const listener of viewers) listener(url);
		if (previous) URL.revokeObjectURL(previous);
	}

	private reconnect(ids: string[], query: string) {
		this.connection?.abort();
		this.connection = undefined;
		if (!ids.length) return;
		const connection = new AbortController();
		this.connection = connection;
		void this.follow(`${this.endpoint()}?${query}`, ids, connection);
	}

	private async follow(url: string, ids: string[], connection: AbortController) {
		try {
			const reader = (await this.read(url, connection.signal)).getReader();
			const records = new PictureRecords();
			while (true) {
				const { value, done } = await reader.read();
				if (done) break;
				for (const { id, picture } of records.read(value)) this.show(id, picture);
			}
		} catch {
			// A connection that was replaced or lost ends here; the viewers are told below.
		}
		if (this.connection !== connection) return;
		this.connection = undefined;
		this.cameras.disconnected();
		for (const id of ids) this.show(id, new Uint8Array(0));
	}
}

type OverlayListener = (frames: CameraOverlayFrame[]) => void;
type Connection = Pick<EventTarget, 'addEventListener'> & { close(): void };

/** One metadata connection per page; camera video stays independent of inference. */
export class CameraOverlays {
	private cameras = new WatchedCameras<OverlayListener>((ids, query) => this.reconnect(ids, query));
	private frames = new Map<string, Map<string, CameraOverlayFrame>>();
	private connection?: Connection;
	private watchdog?: ReturnType<typeof setInterval>;
	private endpoint: () => string;
	private connect: (url: string) => Connection;

	constructor(
		endpoint: () => string,
		connect: (url: string) => Connection = (url) => new EventSource(url)
	) {
		this.endpoint = endpoint;
		this.connect = connect;
	}

	subscribe(id: string, listener: OverlayListener): () => void {
		this.cameras.add(id, listener);
		listener([...(this.frames.get(id)?.values() ?? [])]);
		return () => {
			if (this.cameras.remove(id, listener)) this.frames.delete(id);
			listener([]);
		};
	}

	private notify(id: string) {
		const frames = [...(this.frames.get(id)?.values() ?? [])];
		for (const listener of this.cameras.of(id)) listener(frames);
	}

	private clear() {
		this.frames.clear();
		for (const id of this.cameras.ids()) this.notify(id);
	}

	private reconnect(ids: string[], query: string) {
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
			if (!this.cameras.of(frame.cameraId).size) return;
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

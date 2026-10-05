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
	private viewers = new Map<string, Set<Listener>>();
	private shown = new Map<string, string>();
	/** Cameras whose stream ended; asking for one again needs a new connection. */
	private ended = new Set<string>();
	private connection?: AbortController;
	private connectedIds = '';
	private pending = false;
	private endpoint: () => string;
	private read: Read;

	constructor(endpoint: () => string, read: Read = readPictures) {
		this.endpoint = endpoint;
		this.read = read;
	}

	subscribe(id: string, listener: Listener): () => void {
		const viewers = this.viewers.get(id) ?? new Set<Listener>();
		viewers.add(listener);
		this.viewers.set(id, viewers);
		const shown = this.shown.get(id);
		if (shown) listener(shown);
		if (this.ended.delete(id)) this.connectedIds = '';
		this.schedule();
		return () => {
			viewers.delete(listener);
			if (!viewers.size) {
				this.viewers.delete(id);
				this.forget(id);
			}
			this.schedule();
		};
	}

	/** Several cameras appear or leave together; connect once for all of them. */
	private schedule() {
		if (this.pending) return;
		this.pending = true;
		queueMicrotask(() => {
			this.pending = false;
			this.reconnect();
		});
	}

	private forget(id: string) {
		const shown = this.shown.get(id);
		if (shown) URL.revokeObjectURL(shown);
		this.shown.delete(id);
	}

	private show(id: string, picture: Uint8Array) {
		const viewers = this.viewers.get(id);
		if (!viewers) return;
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

	private reconnect() {
		const ids = [...this.viewers.keys()].sort();
		const query = new URLSearchParams(ids.map((id) => ['camera', id])).toString();
		if (query === this.connectedIds) return;
		this.connectedIds = query;
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
		this.connectedIds = '';
		for (const id of ids) this.show(id, new Uint8Array(0));
	}
}

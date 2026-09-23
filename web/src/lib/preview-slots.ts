/** Limits active camera connections in one browser tab; waiting viewers resume in order. */
export class PreviewSlots {
	private viewers = new Map<symbol, { notify: (active: boolean) => void; active: boolean }>();
	private readonly limit: number;
	constructor(limit = 4) {
		this.limit = limit;
	}

	request(notify: (active: boolean) => void): () => void {
		const key = Symbol();
		this.viewers.set(key, { notify, active: false });
		this.refresh();
		return () => {
			this.viewers.delete(key);
			this.refresh();
		};
	}

	private refresh() {
		let index = 0;
		for (const viewer of this.viewers.values()) {
			const active = index++ < this.limit;
			if (viewer.active === active) continue;
			viewer.active = active;
			viewer.notify(active);
		}
	}
}

export const cameraPreviewSlots = new PreviewSlots();

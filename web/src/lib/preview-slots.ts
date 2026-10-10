/** Limits active camera connections in one browser tab; waiting viewers resume in order. */
export class PreviewSlots {
	private viewers = new Map<symbol, { notify: (active: boolean) => void; active: boolean }>();
	private readonly limit: number;
	constructor(limit = 4) {
		this.limit = limit;
	}

	/** An explicit request takes priority over previews already waiting for a slot. */
	request(notify: (active: boolean) => void, priority = false): () => void {
		const key = Symbol();
		const viewer = { notify, active: false };
		if (priority) this.viewers = new Map([[key, viewer], ...this.viewers]);
		else this.viewers.set(key, viewer);
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

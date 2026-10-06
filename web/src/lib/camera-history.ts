import type { Detection } from './detections.ts';
import type { CameraRuntimeStatus } from './runtime.ts';

/**
 * What a camera was doing: analysed by every detector, on its way there, unreachable, paused by
 * someone, or not known because the application was not running.
 */
export type WatchState = 'watched' | 'connecting' | 'offline' | 'paused' | 'stopped';

/** One change of a camera's state, as kept in the history files. */
export interface WatchChange {
	at: string;
	camera: string;
	state: WatchState;
}

export interface WatchStretch {
	from: string;
	to: string;
	state: WatchState;
}

export interface CameraHistory {
	id: string;
	label: string;
	stretches: WatchStretch[];
	detections: Detection[];
}

export function watchState(state: CameraRuntimeStatus['state']): WatchState {
	if (state === 'monitoring') return 'watched';
	if (state === 'paused') return 'paused';
	return state === 'offline' || state === 'failed' ? 'offline' : 'connecting';
}

/**
 * The stretches of each camera between two moments. A state lasts until the camera's next
 * change; the last one lasts until `until`, the latest moment the application is known to have
 * been running.
 */
export function watchStretches(
	changes: WatchChange[],
	from: Date,
	to: Date,
	until: Date
): Map<string, WatchStretch[]> {
	const cameras = new Map<string, WatchStretch[]>();
	const end = Math.min(to.getTime(), until.getTime());
	const open = new Map<string, WatchChange>();
	const close = (change: WatchChange, at: number) => {
		const start = Math.max(Date.parse(change.at), from.getTime());
		const stop = Math.min(at, end);
		if (stop <= start) return;
		const stretches = cameras.get(change.camera) ?? [];
		const previous = stretches.at(-1);
		if (previous?.state === change.state && Date.parse(previous.to) === start)
			previous.to = new Date(stop).toISOString();
		else
			stretches.push({
				from: new Date(start).toISOString(),
				to: new Date(stop).toISOString(),
				state: change.state
			});
		cameras.set(change.camera, stretches);
	};
	for (const change of changes) {
		const previous = open.get(change.camera);
		if (previous) close(previous, Date.parse(change.at));
		open.set(change.camera, change);
	}
	for (const change of open.values()) close(change, end);
	return cameras;
}

/** How long a camera was watched, in milliseconds. */
export function watchedTime(stretches: WatchStretch[]): number {
	return stretches
		.filter((stretch) => stretch.state === 'watched')
		.reduce((total, stretch) => total + Date.parse(stretch.to) - Date.parse(stretch.from), 0);
}

/** The round moments of a time axis: every `step` milliseconds counted from this computer's midnight. */
export function axisTicks(from: number, to: number, step: number): number[] {
	const midnight = new Date(from).setHours(0, 0, 0, 0);
	const ticks: number[] = [];
	for (
		let tick = midnight + (Math.floor((from - midnight) / step) + 1) * step;
		tick < to;
		tick += step
	)
		ticks.push(tick);
	return ticks;
}

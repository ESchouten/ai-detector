import type { RemoteQuery } from '@sveltejs/kit';
import { createContext } from 'svelte';
import { createSubscriber } from 'svelte/reactivity';
import { afterNavigate } from '$app/navigation';
import { monitoringSummary, type MonitoringSummary } from '../monitoring';
import { getDetectorCount } from '../remote/detector.remote';
import { getRuntime } from '../remote/runtime.remote';
import type { RuntimeStatus } from '../runtime';

interface RuntimeMonitor {
	query: RemoteQuery<RuntimeStatus>;
	/** The latest status, or the first one read. */
	readonly runtime: RuntimeStatus;
	readonly stale: boolean;
	readonly lastCheckedAt: number;
	readonly detectors: number;
	/** What every page says about monitoring, so no two of them can say different things. */
	readonly summary: MonitoringSummary;
	/** Reads the first status and detector count; the pages render once both are known. */
	load(): Promise<void>;
}

export const [useRuntimeStatus, provideRuntimeStatus] = createContext<RuntimeMonitor>();

const UNAVAILABLE: RuntimeStatus = {
	managed: false,
	phase: 'stopped',
	message: 'Status is unavailable.',
	dataDirectory: '',
	readiness: 'idle',
	cameras: []
};

/** One query per layout; Svelte starts polling for the first viewer and stops after the last. */
export function createRuntimeStatus(): RuntimeMonitor {
	const query = getRuntime();
	const count = getDetectorCount();
	let initial = $state(UNAVAILABLE);
	let initialCount = $state(0);
	let lastCheckedAt = $state(Date.now());
	let now = $state(Date.now());
	$effect(() => {
		if (query.current && !query.error) lastCheckedAt = Date.now();
	});
	// Saving a camera or detector ends with a navigation; pick up the new count then.
	afterNavigate(({ type }) => {
		if (type !== 'enter') void count.refresh();
	});
	const subscribe = createSubscriber(() => {
		let active = true;
		const clock = setInterval(() => (now = Date.now()), 1000);
		let timer: ReturnType<typeof setTimeout>;
		async function refresh() {
			// The query retains its last good value and exposes failures through query.error.
			await query.refresh().catch(() => undefined);
			if (active) timer = setTimeout(refresh, 2000);
		}
		void refresh();
		return () => {
			active = false;
			clearTimeout(timer);
			clearInterval(clock);
		};
	});
	const monitor: RuntimeMonitor = {
		query,
		get runtime() {
			return query.current ?? initial;
		},
		get stale() {
			subscribe();
			return Boolean(query.error) || now - lastCheckedAt > 10000;
		},
		get lastCheckedAt() {
			return lastCheckedAt;
		},
		get detectors() {
			return count.current ?? initialCount;
		},
		get summary() {
			return monitoringSummary(monitor.runtime, {
				stale: monitor.stale,
				configured: monitor.detectors > 0
			});
		},
		async load() {
			[initial, initialCount] = await Promise.all([
				// Navigation must render even when status cannot be read; pages report that failure.
				Promise.resolve(query).catch(() => UNAVAILABLE),
				count
			]);
		}
	};
	return monitor;
}

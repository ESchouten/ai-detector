import type { RemoteQuery } from '@sveltejs/kit';
import { createContext } from 'svelte';
import { createSubscriber } from 'svelte/reactivity';
import { getRuntime } from '../remote/runtime.remote';
import type { RuntimeStatus } from '../runtime';

interface RuntimeMonitor {
	query: RemoteQuery<RuntimeStatus>;
	readonly stale: boolean;
	readonly lastCheckedAt: number;
}

export const [useRuntimeStatus, provideRuntimeStatus] = createContext<RuntimeMonitor>();

/** One query per layout; Svelte starts polling for the first viewer and stops after the last. */
export function createRuntimeStatus(): RuntimeMonitor {
	const query = getRuntime();
	let lastCheckedAt = $state(Date.now());
	let now = $state(Date.now());
	$effect(() => {
		if (query.current && !query.error) lastCheckedAt = Date.now();
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
	return {
		query,
		get stale() {
			subscribe();
			return Boolean(query.error) || now - lastCheckedAt > 10000;
		},
		get lastCheckedAt() {
			return lastCheckedAt;
		}
	};
}

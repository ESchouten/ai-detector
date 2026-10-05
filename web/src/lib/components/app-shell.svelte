<script lang="ts">
	import type { Snippet } from 'svelte';
	import { afterNavigate } from '$app/navigation';
	import * as Sidebar from '$lib/components/ui/sidebar/index.js';
	import AppSidebar from './app-sidebar.svelte';
	import MobileHeader from './mobile-header.svelte';
	import MobileNav from './mobile-nav.svelte';
	import { readRuntime, useRuntimeStatus } from '$lib/hooks/runtime-status.svelte';
	import { monitoringSummary } from '$lib/monitoring';
	import { getInstallation } from '$lib/remote/camera-setup.remote';
	import { version } from '$lib/version';

	// Navigation and the monitoring state that is visible from every page.
	let { children }: { children: Snippet } = $props();
	const monitor = useRuntimeStatus();
	const counts = getInstallation();
	// Read once, then follow the queries' current values. Awaiting a polled query reactively
	// would hold back every other update on the page until it answers.
	const [initialRuntime, initialCounts] = await Promise.all([readRuntime(monitor.query), counts]);
	const runtime = $derived(monitor.query.current ?? initialRuntime);
	const installation = $derived(counts.current ?? initialCounts);
	// Saving a camera or detector ends with a navigation; pick up the new counts then.
	afterNavigate(({ type }) => {
		if (type !== 'enter') void counts.refresh();
	});
	const summary = $derived(
		monitoringSummary(runtime, { stale: monitor.stale, configured: installation.detectors > 0 })
	);
</script>

<Sidebar.Provider>
	<AppSidebar {summary} {version} />
	<div class="flex min-w-0 flex-1 flex-col">
		<MobileHeader {summary} />
		<main class="flex-1 px-4 pt-5 pb-28 md:px-8 md:pt-8 md:pb-12">
			<div class="mx-auto w-full max-w-[88rem]">
				{@render children()}
			</div>
		</main>
	</div>
	<MobileNav />
</Sidebar.Provider>

<script lang="ts">
	import type { Snippet } from 'svelte';
	import * as Sidebar from '$lib/components/ui/sidebar/index.js';
	import AppSidebar from './app-sidebar.svelte';
	import HomeScreenHint from './home-screen-hint.svelte';
	import MobileHeader from './mobile-header.svelte';
	import MobileNav from './mobile-nav.svelte';
	import { useRuntimeStatus } from '$lib/hooks/runtime-status.svelte';

	// Navigation and the monitoring state that is visible from every page.
	let { children }: { children: Snippet } = $props();
	const monitor = useRuntimeStatus();
	const summary = $derived(monitor.summary);
</script>

<Sidebar.Provider>
	<AppSidebar {summary} />
	<div class="flex min-w-0 flex-1 flex-col">
		<MobileHeader {summary} />
		<main class="flex-1 px-4 pt-5 pb-28 md:px-8 md:pt-8 md:pb-12">
			<div class="mx-auto w-full max-w-[88rem]">
				<HomeScreenHint />
				{@render children()}
			</div>
		</main>
	</div>
	<MobileNav />
</Sidebar.Provider>

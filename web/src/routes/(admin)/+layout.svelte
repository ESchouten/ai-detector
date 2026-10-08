<script lang="ts">
	import { page } from '$app/state';
	import AppShell from '$lib/components/app-shell.svelte';
	import GuidedHeader from '$lib/components/guided-header.svelte';
	import { createRuntimeStatus, provideRuntimeStatus } from '$lib/hooks/runtime-status.svelte';

	let { children } = $props();
	provideRuntimeStatus(createRuntimeStatus());
	// First-run setup is one guided task; the rest of the app has nothing to show yet.
	const guided = $derived(page.route.id?.startsWith('/(admin)/setup') ?? false);
</script>

{#if guided}
	<div class="flex min-h-svh flex-col">
		<GuidedHeader />
		<main class="flex-1 px-4 pt-6 pb-16 md:px-8 md:pt-10">
			{@render children()}
		</main>
	</div>
{:else}
	<AppShell>{@render children()}</AppShell>
{/if}

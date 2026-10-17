<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { Download, LifeBuoy } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import PageHeader from '$lib/components/page-header.svelte';
	const missing = $derived(page.status === 404);
</script>

<section class="page-narrow">
	<PageHeader
		title={missing ? 'Page not found' : 'This page needs attention'}
		description={page.error?.message}
	/>
	<div class="flex flex-wrap gap-3">
		{#if missing}
			<Button href={resolve('/')}>Go to the start</Button>
		{:else}
			<Button href={resolve('/recovery')}>
				<LifeBuoy data-icon="inline-start" aria-hidden="true" />Recover settings
			</Button>
			<Button href={resolve('/logs/diagnostics')} variant="outline" download>
				<Download data-icon="inline-start" aria-hidden="true" />Download diagnostics
			</Button>
		{/if}
	</div>
</section>

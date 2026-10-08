<script lang="ts">
	import { resolve } from '$app/paths';
	import { CircleAlert, TriangleAlert } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import MonitoringControl from './monitoring-control.svelte';
	import { useRuntimeStatus } from '$lib/hooks/runtime-status.svelte';
	import { monitoringSummary } from '$lib/monitoring';

	// Quiet while monitoring works; says so on the page when cameras are not protected.
	let { configured }: { configured: boolean } = $props();
	const monitor = useRuntimeStatus();
	const initial = monitor.query.current ?? (await monitor.query);
	const runtime = $derived(monitor.query.current ?? initial);
	const summary = $derived(monitoringSummary(runtime, { stale: monitor.stale, configured }));
</script>

{#if summary.attention}
	<div
		role="status"
		class={[
			'flex flex-wrap items-center gap-x-4 gap-y-3 rounded-xl border px-4 py-3',
			summary.tone === 'bad'
				? 'border-danger-foreground/15 bg-danger text-danger-foreground'
				: 'border-warning-foreground/15 bg-warning text-warning-foreground'
		]}
	>
		{#if summary.tone === 'bad'}<CircleAlert class="size-5 shrink-0" aria-hidden="true" />
		{:else}<TriangleAlert class="size-5 shrink-0" aria-hidden="true" />{/if}
		<div class="flex min-w-0 flex-1 basis-64 flex-col">
			<p class="text-sm font-semibold">{summary.label}</p>
			<p class="text-sm break-words opacity-90">{summary.detail}</p>
		</div>
		<div class="flex flex-wrap items-center gap-2">
			{#if summary.action === 'start' || summary.action === 'retry'}
				<MonitoringControl action={summary.action} size="sm" />
			{/if}
			<Button href={resolve('/status')} variant="ghost" size="sm">Details</Button>
		</div>
	</div>
{/if}

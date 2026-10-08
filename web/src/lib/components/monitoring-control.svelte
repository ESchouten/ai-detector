<script lang="ts">
	import { LoaderCircle, Pause, Play, RotateCw, X } from '@lucide/svelte';
	import { toast } from 'svelte-sonner';
	import { Button, type ButtonSize } from '$lib/components/ui/button';
	import { useRuntimeStatus } from '$lib/hooks/runtime-status.svelte';
	import type { MonitoringAction } from '$lib/monitoring';
	import { errorMessage } from '$lib/remote-errors';
	import { startDetector, stopDetector } from '$lib/remote/runtime.remote';

	let {
		action,
		size = 'default',
		quiet = false
	}: {
		action: MonitoringAction | null;
		size?: ButtonSize;
		/** Use the outline style, for places where this is not the main thing to do. */
		quiet?: boolean;
	} = $props();
	const monitor = useRuntimeStatus();
	let pending = $state(false);
	const labels: Record<MonitoringAction, string> = {
		start: 'Start monitoring',
		retry: 'Try again',
		cancel: 'Cancel',
		pause: 'Pause monitoring'
	};
	const starts = $derived(action === 'start' || action === 'retry');

	async function run() {
		pending = true;
		try {
			await (starts ? startDetector() : stopDetector()).updates(monitor.query);
		} catch (cause) {
			toast.error(
				errorMessage(
					cause,
					'The request could not be completed. Check that AI Detector is still open.'
				)
			);
		} finally {
			pending = false;
		}
	}
</script>

{#if action}
	<Button
		{size}
		variant={starts && !quiet ? 'default' : 'outline'}
		disabled={pending || monitor.stale}
		onclick={run}
	>
		{#if pending}<LoaderCircle
				data-icon="inline-start"
				class="animate-spin"
				aria-hidden="true"
			/>{:else if action === 'start'}<Play
				data-icon="inline-start"
				aria-hidden="true"
			/>{:else if action === 'retry'}<RotateCw
				data-icon="inline-start"
				aria-hidden="true"
			/>{:else if action === 'cancel'}<X data-icon="inline-start" aria-hidden="true" />{:else}<Pause
				data-icon="inline-start"
				aria-hidden="true"
			/>{/if}
		{labels[action]}
	</Button>
{/if}

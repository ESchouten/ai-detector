<script lang="ts">
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
	import LiveDetections from '$lib/components/live-detections.svelte';
	import { cameraPreviewSlots } from '$lib/preview-slots';
	let { id, label, monitored }: { id: string; label: string; monitored: boolean } = $props();
	let mode = $state<'picture' | 'detections' | null>(null);
	let failed = $state(false);
	let version = $state(0);
	let container: HTMLDivElement;
	let visible = $state(false);
	let pageVisible = $state(false);
	let active = $state(false);

	onMount(() => {
		const observer = new IntersectionObserver(([entry]) => (visible = entry.isIntersecting));
		observer.observe(container);
		const visibilityChanged = () => (pageVisible = document.visibilityState === 'visible');
		visibilityChanged();
		document.addEventListener('visibilitychange', visibilityChanged);
		return () => {
			observer.disconnect();
			document.removeEventListener('visibilitychange', visibilityChanged);
		};
	});

	$effect(() => {
		if (!mode || !visible || !pageVisible) return;
		const release = cameraPreviewSlots.request((value) => (active = value));
		return () => {
			release();
			active = false;
		};
	});

	function toggle(next: 'picture' | 'detections') {
		mode = mode === next ? null : next;
		failed = false;
	}

	function releaseImage(node: HTMLImageElement) {
		return { destroy: () => (node.src = 'data:,') };
	}
</script>

<div bind:this={container} class="flex flex-col gap-3">
	<div class="flex flex-wrap gap-2">
		<Button
			type="button"
			variant="outline"
			aria-pressed={mode === 'picture'}
			onclick={() => toggle('picture')}
		>
			{mode === 'picture' ? 'Hide live picture' : 'Show live picture'}
		</Button>
		{#if monitored}
			<Button
				type="button"
				variant="outline"
				aria-pressed={mode === 'detections'}
				onclick={() => toggle('detections')}
			>
				{mode === 'detections' ? 'Hide detections' : 'Show detections'}
			</Button>
		{/if}
	</div>
	{#if mode}
		{#if !active}
			<p role="status" class="text-sm text-muted-foreground">
				{!visible || !pageVisible
					? 'Preview paused while out of view.'
					: 'Four previews are already open. Close one or scroll it out of view to resume this preview.'}
			</p>
		{:else if mode === 'detections'}
			<LiveDetections {id} {label} />
		{:else}
			{#key version}
				<img
					use:releaseImage
					src={resolve(`/cameras/${id}/preview`)}
					alt={`${label} live picture`}
					onload={() => (failed = false)}
					onerror={() => (failed = true)}
					class="aspect-video w-full rounded-md bg-muted object-contain"
				/>
			{/key}
			<p role="status" class="text-sm text-muted-foreground">
				{failed
					? 'The live picture is unavailable. Check the camera connection in Camera settings.'
					: 'If the picture freezes or disappears, retry the live picture.'}
			</p>
			<Button
				type="button"
				variant="outline"
				onclick={() => {
					failed = false;
					version += 1;
				}}>Retry picture</Button
			>
		{/if}
	{/if}
</div>

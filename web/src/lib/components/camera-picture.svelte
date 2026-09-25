<script lang="ts">
	import { onMount, type Snippet } from 'svelte';
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
	import { Badge } from '$lib/components/ui/badge';
	import CardOverlay from './card-overlay.svelte';
	import { cameraPreviewSlots } from '$lib/preview-slots';
	let {
		id,
		label,
		overlay: overlayContent,
		class: className
	}: { id: string; label: string; overlay?: Snippet; class?: string } = $props();
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
		if (!visible || !pageVisible) return;
		const release = cameraPreviewSlots.request((value) => (active = value), version > 0);
		return () => {
			release();
			active = false;
		};
	});

	function releaseImage(node: HTMLImageElement) {
		return { destroy: () => (node.src = 'data:,') };
	}
</script>

<div bind:this={container}>
	<CardOverlay class={className}>
		<div class="relative aspect-video bg-muted">
			{#if active}
				{#key version}
					<img
						use:releaseImage
						src={resolve(`/cameras/${id}/preview`)}
						alt={`${label} live picture`}
						onload={() => (failed = false)}
						onerror={() => (failed = true)}
						class="size-full object-contain"
					/>
				{/key}
			{/if}
			{#if !active || failed}
				<div
					class="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-muted px-4 pt-12 pb-4"
				>
					<p role="status" class="text-center text-sm text-muted-foreground">
						{active ? 'The live picture is unavailable.' : 'Preview paused'}
					</p>
					{#if visible && pageVisible}
						<Button
							type="button"
							variant="outline"
							size="sm"
							onclick={() => {
								failed = false;
								version += 1;
							}}>{active ? 'Retry picture' : 'Show live picture'}</Button
						>
					{/if}
				</div>
			{/if}
		</div>
		{#snippet overlay()}
			{#if overlayContent}{@render overlayContent()}{:else}<Badge
					variant="secondary"
					class="max-w-full text-left whitespace-normal">{label}</Badge
				>{/if}
		{/snippet}
	</CardOverlay>
</div>

<script lang="ts">
	import { onMount, type Snippet } from 'svelte';
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
	import CameraDetections from './camera-detections.svelte';
	import { cameraPreviewSlots } from '$lib/preview-slots';
	import { cn } from '$lib/utils';
	let {
		id,
		label,
		monitored = false,
		caption,
		corner,
		class: className
	}: {
		id: string;
		label: string;
		monitored?: boolean;
		/** Replaces the camera name along the bottom of the picture. */
		caption?: Snippet;
		/** Controls in the top corner, above the picture. */
		corner?: Snippet;
		class?: string;
	} = $props();
	let failed = $state(false);
	let loaded = $state(false);
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
			loaded = false;
		};
	});

	function releaseImage(node: HTMLImageElement) {
		return { destroy: () => (node.src = 'data:,') };
	}
</script>

<div
	bind:this={container}
	class={cn(
		'relative aspect-video overflow-hidden rounded-xl bg-media text-media-foreground',
		className
	)}
>
	{#if active}
		{#key version}
			<img
				use:releaseImage
				src={resolve(`/cameras/${id}/preview`)}
				alt={`${label} live picture`}
				onload={() => {
					failed = false;
					loaded = true;
				}}
				onerror={({ currentTarget }) => {
					// Releasing a picture that left the page also ends in an error event; that is not a failure.
					if (currentTarget.isConnected) failed = true;
				}}
				class="size-full object-contain"
			/>
		{/key}
	{/if}
	{#if active && !failed && monitored}<CameraDetections {id} {label} />{/if}
	{#if active && !failed && !loaded}
		<p
			role="status"
			class="absolute inset-0 flex items-center justify-center pb-6 text-sm text-media-foreground/70"
		>
			Connecting…
		</p>
	{/if}
	{#if !active || failed}
		<div class="absolute inset-0 flex flex-col items-center justify-center gap-3 px-4 pb-6">
			<p role="status" class="text-center text-sm text-media-foreground/70">
				{active ? 'The live picture is unavailable.' : 'Preview paused'}
			</p>
			{#if visible && pageVisible}
				<Button
					type="button"
					variant="secondary"
					size="sm"
					class="relative z-20"
					onclick={() => {
						failed = false;
						loaded = false;
						version += 1;
					}}>{active ? 'Try again' : 'Show live picture'}</Button
				>
			{/if}
		</div>
	{/if}
	<div
		class="pointer-events-none absolute inset-x-0 bottom-0 flex items-end bg-linear-to-t from-black/80 via-black/35 to-transparent px-3.5 pt-10 pb-3"
	>
		{#if caption}{@render caption()}{:else}
			<p class="min-w-0 truncate text-sm font-medium">{label}</p>
		{/if}
	</div>
	{#if corner}
		<div class="absolute top-2.5 right-2.5 z-20">{@render corner()}</div>
	{/if}
</div>

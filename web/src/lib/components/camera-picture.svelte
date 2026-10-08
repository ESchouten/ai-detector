<script lang="ts" module>
	import { resolve } from '$app/paths';
	import { CameraPictures } from '$lib/camera-pictures';
	const pictures = new CameraPictures(() => resolve('/cameras/pictures'));
</script>

<script lang="ts">
	import { onMount, type Snippet } from 'svelte';
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
	let picture = $state<string>();
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

	$effect(() => {
		// Asking again after a failure is a new subscription.
		void version;
		if (!active) return;
		const release = pictures.subscribe(id, (url) => {
			if (url) picture = url;
			else failed = true;
		});
		return () => {
			release();
			picture = undefined;
		};
	});
</script>

<div
	bind:this={container}
	class={cn(
		'relative aspect-video overflow-hidden rounded-xl bg-media text-media-foreground',
		className
	)}
>
	{#if active && picture && !failed}
		<img src={picture} alt={`${label} live picture`} class="size-full object-contain" />
	{/if}
	{#if active && !failed && monitored}<CameraDetections {id} {label} />{/if}
	{#if active && !failed && !picture}
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

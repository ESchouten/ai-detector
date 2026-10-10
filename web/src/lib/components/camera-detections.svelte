<script lang="ts" module>
	import { resolve } from '$app/paths';
	import { CameraOverlays } from '$lib/camera-overlays';
	const overlays = new CameraOverlays(() => resolve('/cameras/live'));
</script>

<script lang="ts">
	import { detectionBoxLabel, type CameraOverlayFrame } from '$lib/live-preview';
	import DetectionBoxes from './detection-boxes.svelte';
	let { id, label }: { id: string; label: string } = $props();
	let frames = $state<CameraOverlayFrame[]>([]);
	let width = $state(0);
	let height = $state(0);
	$effect(() =>
		overlays.subscribe(id, (value) => {
			frames = value;
		})
	);
</script>

<div
	class="pointer-events-none absolute inset-0"
	bind:clientWidth={width}
	bind:clientHeight={height}
>
	{#each frames as frame (frame.ruleId)}
		{#if frame.boxes.length}
			<svg
				viewBox={`0 0 ${frame.image.width} ${frame.image.height}`}
				preserveAspectRatio="xMidYMid meet"
				class="absolute inset-0 size-full"
				role="img"
				aria-label={`${label} · ${frame.ruleLabel}: ${frame.boxes.map(detectionBoxLabel).join('; ')}`}
			>
				<DetectionBoxes
					{frame}
					displayWidth={Math.min(width, (height * frame.image.width) / frame.image.height)}
				/>
			</svg>
		{/if}
	{/each}
</div>

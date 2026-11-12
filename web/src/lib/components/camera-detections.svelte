<script lang="ts" module>
	import { resolve } from '$app/paths';
	import { CameraOverlays } from '$lib/camera-pictures';
	const overlays = new CameraOverlays(() => resolve('/cameras/live'));
</script>

<script lang="ts">
	import { detectionBoxLabel, type CameraOverlayFrame, type DetectionBox } from '$lib/live-preview';
	import DetectionBoxes from './detection-boxes.svelte';
	import IdentityPills from './identity-pills.svelte';
	let {
		id,
		label,
		onselect,
		selected
	}: {
		id: string;
		label: string;
		/** Makes boxes with an identity buttons, for naming who they are. */
		onselect?: (box: DetectionBox) => void;
		/** The sighting being named; its outline stands out. */
		selected?: string;
	} = $props();
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
				role={onselect ? 'group' : 'img'}
				aria-label={`${label} · ${frame.ruleLabel}: ${frame.boxes.map(detectionBoxLabel).join('; ')}`}
			>
				<DetectionBoxes
					{frame}
					displayWidth={Math.min(width, (height * frame.image.width) / frame.image.height)}
					{onselect}
					{selected}
				/>
			</svg>
			<IdentityPills {frame} {width} {height} {onselect} {selected} />
		{/if}
	{/each}
</div>

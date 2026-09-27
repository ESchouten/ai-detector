<script lang="ts">
	import { badgeHue } from '$lib/badge-colors';
	import { detectionBoxLabel, type CameraOverlayFrame } from '$lib/live-preview';
	let {
		frame,
		displayWidth
	}: {
		frame: Omit<CameraOverlayFrame, 'cameraId'>;
		displayWidth: number;
	} = $props();
	const fontSize = $derived(Math.max(14, (frame.image.width / Math.max(1, displayWidth)) * 12));
	const color = $derived(`oklch(0.8 0.14 ${badgeHue(frame.rulePreset ?? frame.ruleLabel)})`);
</script>

{#each frame.boxes as box, index (index)}
	<rect
		x={box.x1}
		y={box.y1}
		width={box.x2 - box.x1}
		height={box.y2 - box.y1}
		fill="none"
		stroke={color}
		stroke-width="2"
		vector-effect="non-scaling-stroke"
	/>
	<text
		x={box.x1 + 4}
		y={Math.max(fontSize + 3, box.y1 - 5)}
		font-size={fontSize}
		font-weight="600"
		fill="white"
		stroke="black"
		stroke-width="3"
		paint-order="stroke"
		stroke-linejoin="round">{detectionBoxLabel(box)}</text
	>
{/each}

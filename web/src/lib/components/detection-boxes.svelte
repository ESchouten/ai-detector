<script lang="ts">
	import { badgeHue } from '$lib/badge-colors';
	import {
		boxOutline,
		detectionBoxLabel,
		showsPill,
		type DetectionBox,
		type LivePreviewFrame
	} from '$lib/live-preview';
	let {
		frame,
		displayWidth,
		onselect,
		selected
	}: {
		frame: LivePreviewFrame;
		displayWidth: number;
		/** Makes boxes with an identity buttons, for naming who they are. */
		onselect?: (box: DetectionBox) => void;
		/** The sighting being named; its outline stands out. */
		selected?: string;
	} = $props();
	const fontSize = $derived(Math.max(14, (frame.image.width / Math.max(1, displayWidth)) * 12));
	const color = $derived(`oklch(0.8 0.14 ${badgeHue(frame.rulePreset ?? frame.ruleLabel)})`);
</script>

{#each frame.boxes as box, index (index)}
	{@const chosen = selected !== undefined && box.identity?.sighting === selected}
	{#if onselect && box.identity}
		<polygon
			points={boxOutline(box)}
			fill="transparent"
			stroke={chosen ? 'white' : color}
			stroke-width={chosen ? 4 : 2}
			stroke-linejoin="round"
			vector-effect="non-scaling-stroke"
			role="button"
			tabindex="0"
			aria-label={`Name ${detectionBoxLabel(box)}`}
			class={[
				'pointer-events-auto cursor-pointer outline-none hover:fill-white/15 focus-visible:fill-white/25',
				chosen && 'fill-white/25'
			]}
			onclick={() => onselect(box)}
			onkeydown={(event) => {
				if (event.key !== /* @wc-ignore */ 'Enter' && event.key !== ' ') return;
				event.preventDefault();
				onselect(box);
			}}
		/>
	{:else}
		<polygon
			points={boxOutline(box)}
			fill="none"
			stroke={color}
			stroke-width="2"
			stroke-linejoin="round"
			vector-effect="non-scaling-stroke"
		/>
	{/if}
	<!-- While naming, an outline waits for its pill without a label. -->
	{#if !onselect && !showsPill(box, false)}
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
	{/if}
{/each}

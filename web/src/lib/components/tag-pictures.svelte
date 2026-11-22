<script lang="ts">
	import { resolve } from '$app/paths';
	import type { Sighting } from '$lib/individuals';
	let { sighting, tag }: { sighting: Sighting; tag: NonNullable<Sighting['tag']> } = $props();
	let width = $state(0);
	let height = $state(0);
	const [x, y] = $derived(tag.box);
	const size = $derived({ width: tag.box[2] - x, height: tag.box[3] - y });
</script>

<!-- The picture a number was read from, with the tag marked, and beside it the tag enlarged, so a
	person can check the number. -->
<div class="flex gap-2">
	<div class="relative size-28 shrink-0 overflow-hidden rounded-lg bg-media">
		<img
			src={resolve(`/identities/${sighting.id}/tag-picture.jpg`)}
			alt=""
			decoding="async"
			class="size-full object-contain"
			bind:naturalWidth={width}
			bind:naturalHeight={height}
		/>
		{#if width && height}
			<svg
				viewBox={`0 0 ${width} ${height}`}
				preserveAspectRatio="xMidYMid meet"
				class="pointer-events-none absolute inset-0 size-full"
				aria-hidden="true"
			>
				<rect
					{x}
					{y}
					{...size}
					fill="none"
					stroke="black"
					stroke-opacity="0.6"
					stroke-width="4"
					vector-effect="non-scaling-stroke"
				/>
				<rect
					{x}
					{y}
					{...size}
					fill="none"
					stroke="oklch(0.9 0.17 95)"
					stroke-width="2"
					vector-effect="non-scaling-stroke"
				/>
			</svg>
		{/if}
	</div>
	<div class="size-28 shrink-0 overflow-hidden rounded-lg bg-media">
		<img
			src={resolve(`/identities/${sighting.id}/tag-read.jpg`)}
			alt=""
			decoding="async"
			class="size-full object-contain"
		/>
	</div>
</div>

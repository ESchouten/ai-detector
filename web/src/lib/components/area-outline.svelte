<script lang="ts">
	import type { Area } from '$lib/detector-editor';
	let {
		area,
		size,
		corners = false
	}: {
		area: Area;
		/** The picture's size in pixels. */
		size: { width: number; height: number };
		/** Mark each corner, while the area is being drawn. */
		corners?: boolean;
	} = $props();
	const points = $derived(area.map(([x, y]) => [x * size.width, y * size.height]));
</script>

<svg
	viewBox={`0 0 ${size.width} ${size.height}`}
	preserveAspectRatio="xMidYMid meet"
	class="pointer-events-none absolute inset-0 size-full"
	aria-hidden="true"
>
	<polygon
		points={points.join(' ')}
		fill="white"
		fill-opacity="0.15"
		stroke="white"
		stroke-width="2"
		vector-effect="non-scaling-stroke"
	/>
	{#if corners}
		{#each points as [x, y], index (index)}
			<circle
				cx={x}
				cy={y}
				r={Math.max(size.width, size.height) / 120}
				fill="white"
				stroke="black"
				stroke-width="1"
				vector-effect="non-scaling-stroke"
			/>
		{/each}
	{/if}
</svg>

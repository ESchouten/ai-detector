<script lang="ts">
	import { resolve } from '$app/paths';
	import type { ClassValue } from 'svelte/elements';
	import type { Sighting } from '$lib/individuals';
	let {
		sighting,
		index = 0,
		loading,
		class: className
	}: {
		sighting: Sighting;
		/** Which of its pictures, from 0. */
		index?: number;
		loading?: 'lazy' | 'eager';
		class?: ClassValue;
	} = $props();
	let width = $state(0);
	let height = $state(0);
	const points = $derived(sighting.outlines[index]?.join(' ') ?? '');
</script>

<!-- Fills its parent, which positions it. The picture keeps its background, so the outline shows
	which one it is. -->
<img
	src={resolve(`/identities/${sighting.id}/crop-${index + 1}.jpg`)}
	alt=""
	{loading}
	decoding="async"
	class={['size-full object-contain', className]}
	bind:naturalWidth={width}
	bind:naturalHeight={height}
/>
{#if points && width && height}
	<svg
		viewBox={`0 0 ${width} ${height}`}
		preserveAspectRatio="xMidYMid meet"
		class={['pointer-events-none absolute inset-0 size-full', className]}
		aria-hidden="true"
	>
		<polygon
			{points}
			fill="none"
			stroke="black"
			stroke-opacity="0.6"
			stroke-width="4"
			stroke-linejoin="round"
			vector-effect="non-scaling-stroke"
		/>
		<polygon
			{points}
			fill="none"
			stroke="oklch(0.9 0.17 95)"
			stroke-width="2"
			stroke-linejoin="round"
			vector-effect="non-scaling-stroke"
		/>
	</svg>
{/if}

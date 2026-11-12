<script lang="ts">
	import { Check, Plus } from '@lucide/svelte';
	import {
		detectionBoxLabel,
		identityLabel,
		identityState,
		pillAnchor,
		showsPill,
		type DetectionBox,
		type IdentityState,
		type LivePreviewFrame
	} from '$lib/live-preview';
	let {
		frame,
		width,
		height,
		onselect,
		selected
	}: {
		frame: LivePreviewFrame;
		/** The overlay's size; the picture is fitted inside it, as the boxes are. */
		width: number;
		height: number;
		/** Makes the pills buttons, for naming who they are. */
		onselect?: (box: DetectionBox) => void;
		/** The sighting being named; its pill stands out. */
		selected?: string;
	} = $props();
	const scale = $derived(Math.min(width / frame.image.width, height / frame.image.height));
	const left = $derived((width - frame.image.width * scale) / 2);
	const top = $derived((height - frame.image.height * scale) / 2);
	const small = $derived(frame.image.width * scale < 480);
	// Nearer individuals are lower in the picture; their pills go on top.
	const pills = $derived(
		frame.boxes
			.filter((box) => showsPill(box, onselect !== undefined))
			.map((box) => ({ box, anchor: pillAnchor(box) }))
			.sort((a, b) => a.anchor[1] - b.anchor[1])
	);
	const caps: Record<IdentityState, string> = {
		recognised: 'bg-blue-600 text-white',
		resembles: 'bg-amber-400 text-neutral-900',
		unnamed: 'bg-neutral-600 text-white'
	};
	const tails: Record<IdentityState, string> = {
		recognised: 'fill-blue-600',
		resembles: 'fill-amber-400',
		unnamed: 'fill-neutral-600'
	};
</script>

{#snippet pill(box: DetectionBox, state: IdentityState, flipped: boolean, chosen: boolean)}
	<svg
		viewBox="0 0 20 10"
		class={[
			'absolute bottom-0',
			small ? 'h-2 w-4' : 'h-2.5 w-5',
			flipped ? 'right-0 -scale-x-100' : 'left-0',
			flipped || state === 'unnamed' ? tails[state] : 'fill-white'
		]}
		aria-hidden="true"
	>
		<polygon points="0,10 9,0 19,2" />
	</svg>
	<span
		class={[
			'flex overflow-hidden rounded-full leading-none font-semibold',
			small ? 'mb-1.5 h-5 text-[0.6875rem]' : 'mb-2 h-7 text-sm',
			flipped ? 'mr-1.5' : 'ml-1.5',
			chosen && 'ring-2 ring-white'
		]}
	>
		{#if state !== 'unnamed'}
			<span
				class={[
					'flex items-center bg-white text-neutral-800 tabular-nums',
					small ? 'px-1.5' : 'px-2.5'
				]}>{identityLabel(box.identity)?.replace(/\?$/, '')}</span
			>
		{/if}
		<span
			class={[
				'flex items-center justify-center',
				small ? 'min-w-5 px-1' : 'min-w-7 px-1.5',
				caps[state]
			]}
		>
			{#if state === 'recognised'}
				<Check class={small ? 'size-3' : 'size-4'} strokeWidth={3} />
			{:else if state === 'resembles'}
				<span class="font-bold">?</span>
			{:else}
				<Plus class={small ? 'size-3' : 'size-4'} strokeWidth={3} />
			{/if}
		</span>
	</span>
{/snippet}

{#each pills as { box, anchor: [x, y] }, index (index)}
	{#if box.identity}
		{@const state = identityState(box.identity)}
		{@const flipped = x > frame.image.width * 0.75}
		{@const chosen = box.identity.sighting === selected}
		{@const place = [
			'absolute flex -translate-y-full drop-shadow-md',
			flipped && '-translate-x-full'
		]}
		{#if onselect}
			<!-- The outline is the button people reach by keyboard; the pill is a bigger target. -->
			<button
				type="button"
				tabindex={-1}
				aria-hidden="true"
				class={[...place, 'pointer-events-auto cursor-pointer']}
				style:left="{left + x * scale}px"
				style:top="max({top + y * scale}px, {small ? 1.75 : 2.5}rem)"
				onclick={() => onselect(box)}
			>
				{@render pill(box, state, flipped, chosen)}
			</button>
		{:else}
			<div
				class={place}
				style:left="{left + x * scale}px"
				style:top="max({top + y * scale}px, {small ? 1.75 : 2.5}rem)"
				title={detectionBoxLabel(box)}
			>
				{@render pill(box, state, flipped, chosen)}
			</div>
		{/if}
	{/if}
{/each}

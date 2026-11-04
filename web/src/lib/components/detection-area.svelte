<script lang="ts">
	import { untrack } from 'svelte';
	import { Button } from '$lib/components/ui/button';
	import * as Dialog from '$lib/components/ui/dialog';
	import type { Area } from '$lib/detector-editor';
	import AreaOutline from './area-outline.svelte';
	import CameraPicture from './camera-picture.svelte';
	let {
		camera,
		area: saved,
		onDone
	}: {
		camera: { id: string; label: string };
		area: Area;
		/** Called with the chosen area, empty for the whole picture. */
		onDone: (area: Area) => void;
	} = $props();
	let area = $state<Area>(untrack(() => structuredClone(saved)));

	/** The tapped point as fractions of the picture, which `object-contain` centres in the box. */
	function addCorner(event: MouseEvent, size: { width: number; height: number }) {
		const box = (event.currentTarget as HTMLElement).getBoundingClientRect();
		const scale = Math.min(box.width / size.width, box.height / size.height);
		const fraction = (offset: number, length: number, shown: number) =>
			Math.min(1, Math.max(0, (offset - (length - shown) / 2) / shown));
		area.push([
			fraction(event.clientX - box.left, box.width, size.width * scale),
			fraction(event.clientY - box.top, box.height, size.height * scale)
		]);
	}
</script>

<Dialog.Header>
	<Dialog.Title>Detection area · {camera.label}</Dialog.Title>
	<Dialog.Description>
		Tap the corners of the area to watch. A detection counts when the middle of its box is inside
		it.
	</Dialog.Description>
</Dialog.Header>
<CameraPicture id={camera.id} label={camera.label}>
	{#snippet overlay(size)}
		{#if area.length}<AreaOutline {area} {size} corners />{/if}
		<button
			type="button"
			class="absolute inset-0 z-10 cursor-crosshair"
			aria-label="Add a corner here"
			onclick={(event) => addCorner(event, size)}
		></button>
	{/snippet}
</CameraPicture>
<Dialog.Footer class="gap-2 sm:justify-between">
	<div class="flex gap-2">
		<Button variant="outline" disabled={!area.length} onclick={() => area.pop()}>Undo corner</Button
		>
		<Button variant="outline" disabled={!area.length} onclick={() => (area = [])}>Clear</Button>
	</div>
	<Button
		disabled={area.length > 0 && area.length < 3}
		onclick={() => onDone($state.snapshot(area))}
		>{area.length ? 'Save area' : 'Watch the whole picture'}</Button
	>
</Dialog.Footer>

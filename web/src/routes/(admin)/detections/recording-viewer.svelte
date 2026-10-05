<script lang="ts">
	import { ChevronLeft, ChevronRight } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import * as Dialog from '$lib/components/ui/dialog';
	import Pill from '$lib/components/pill.svelte';
	import { detectionKey, recordingVerdict, type Detection } from '$lib/detections';
	import { clipLength, dayHeading, percent, timeOfDay } from '$lib/format';
	import ReviewButtons from './review-buttons.svelte';
	import { categoryName, recordingMedia } from './media';

	// One recording at a time, with the neighbours a key press away.
	let {
		entries,
		selected = $bindable(),
		colorSeeds,
		onreview
	}: {
		entries: Detection[];
		/** Key of the open recording, or null when closed. */
		selected: string | null;
		colorSeeds: Record<string, string>;
		onreview: (entry: Detection) => void;
	} = $props();
	const index = $derived(entries.findIndex((entry) => detectionKey(entry) === selected));
	const entry = $derived(index >= 0 ? entries[index] : undefined);
	const verdict = $derived(entry ? recordingVerdict(entry) : null);
	// A review can move the recording out of the current filter; remember where it was.
	let position = $state(0);
	$effect(() => {
		if (index >= 0) position = index;
		else if (selected !== null)
			selected = entries.length
				? detectionKey(entries[Math.min(position, entries.length - 1)])
				: null;
	});

	function step(offset: number) {
		const next = entries[index + offset];
		if (next) selected = detectionKey(next);
	}
	function keydown(event: KeyboardEvent) {
		if (event.target instanceof HTMLInputElement) return;
		if (event.key === 'ArrowLeft') step(-1);
		else if (event.key === 'ArrowRight') step(1);
		else return;
		event.preventDefault();
	}
</script>

<Dialog.Root
	open={selected !== null}
	onOpenChange={(open) => {
		if (!open) selected = null;
	}}
>
	<Dialog.Content
		class="flex max-h-[100dvh] flex-col gap-0 overflow-hidden p-0 sm:max-w-4xl"
		onkeydown={keydown}
	>
		{#if entry}
			<Dialog.Header class="gap-1 px-5 pt-5 pr-12 pb-4 text-left">
				<Dialog.Title class="flex flex-wrap items-center gap-x-2.5 gap-y-1.5 text-base">
					<span class="tabular-nums">
						{dayHeading(entry.timestamp.slice(0, 10))}, {timeOfDay(entry.start)}
					</span>
					<Pill tone="category" seed={colorSeeds[entry.type] ?? entry.type}>
						{categoryName(entry.type)}
					</Pill>
					{#if verdict?.tone === 'warn'}<Pill tone="warn">{verdict.label}</Pill>{/if}
				</Dialog.Title>
				<Dialog.Description>
					<span class="flex flex-wrap gap-x-1">
						{#if verdict}<span>{verdict.source}</span><span aria-hidden="true">·</span>{/if}
						<span>{percent(entry.confidence)} confidence</span>
						<span aria-hidden="true">·</span>
						<span>{clipLength(entry.duration)}</span>
					</span>
					{#if verdict?.detail}<span class="block break-words">{verdict.detail}</span>{/if}
				</Dialog.Description>
			</Dialog.Header>
			{#key selected}
				<video
					class="max-h-[62dvh] min-h-0 w-full flex-1 bg-media"
					controls
					autoplay
					playsinline
					poster={recordingMedia(entry, 'best.jpg')}
				>
					<source src={recordingMedia(entry, 'video.mp4')} type="video/mp4" />
					Your browser cannot play this video.
				</video>
			{/key}
			<div class="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
				<div class="flex items-center gap-1.5">
					<Button
						variant="outline"
						size="icon-sm"
						disabled={index <= 0}
						onclick={() => step(-1)}
						aria-label="Newer recording"
						title="Newer (←)"><ChevronLeft aria-hidden="true" /></Button
					>
					<Button
						variant="outline"
						size="icon-sm"
						disabled={index >= entries.length - 1}
						onclick={() => step(1)}
						aria-label="Older recording"
						title="Older (→)"><ChevronRight aria-hidden="true" /></Button
					>
					<span class="pl-1.5 text-xs text-muted-foreground tabular-nums">
						{index + 1} of {entries.length}
					</span>
				</div>
				<ReviewButtons {entry} {onreview} labels />
			</div>
		{/if}
	</Dialog.Content>
</Dialog.Root>

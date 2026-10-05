<script lang="ts">
	import { Play } from '@lucide/svelte';
	import Pill from '$lib/components/pill.svelte';
	import { recordingVerdict, type Detection } from '$lib/detections';
	import { clipLength, percent, timeOfDay } from '$lib/format';
	import ReviewButtons from './review-buttons.svelte';
	import { categoryName, recordingMedia } from './media';

	let {
		entry,
		colorSeed,
		onopen,
		onreview
	}: {
		entry: Detection;
		colorSeed?: string;
		onopen: () => void;
		onreview: (entry: Detection) => void;
	} = $props();
	const verdict = $derived(recordingVerdict(entry));
	const time = $derived(timeOfDay(entry.start));
	const dismissed = $derived(entry.stage === 'rejected');
</script>

<article class="flex min-w-0 flex-col gap-2.5">
	<button
		type="button"
		onclick={onopen}
		aria-label={`Play ${categoryName(entry.type)} recording from ${time}`}
		class="group relative aspect-video overflow-hidden rounded-xl bg-media outline-none focus-visible:ring-[3px] focus-visible:ring-ring/60"
	>
		<img
			src={recordingMedia(entry, 'best.jpg')}
			alt=""
			loading="lazy"
			decoding="async"
			class={[
				'size-full object-contain transition-[opacity,transform] duration-200 group-hover:scale-[1.02]',
				dismissed && 'opacity-55 group-hover:opacity-100'
			]}
		/>
		<span
			class="absolute inset-0 flex items-center justify-center bg-black/0 transition-colors group-hover:bg-black/15"
			aria-hidden="true"
		>
			<span
				class="flex size-12 items-center justify-center rounded-full bg-black/55 text-white opacity-0 backdrop-blur-sm transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
			>
				<Play class="size-5 translate-x-px fill-current" />
			</span>
		</span>
		<span
			class="absolute right-2 bottom-2 rounded-md bg-black/65 px-1.5 py-0.5 text-xs font-medium text-white tabular-nums"
		>
			{clipLength(entry.duration)}
		</span>
	</button>
	<div class="flex items-start justify-between gap-3">
		<div class="flex min-w-0 flex-col gap-1">
			<div class="flex flex-wrap items-center gap-x-2 gap-y-1">
				<time datetime={entry.start} class="text-sm font-semibold tabular-nums">{time}</time>
				<Pill tone="category" seed={colorSeed ?? entry.type}>{categoryName(entry.type)}</Pill>
				{#if verdict?.tone === 'warn'}
					<Pill tone="warn" title={verdict.detail}>{verdict.label}</Pill>
				{/if}
			</div>
			<!-- Separate pieces, so each is a whole phrase to translate; the gaps supply the spaces. -->
			<p class="flex flex-wrap gap-x-1 text-xs text-muted-foreground">
				{#if verdict}<span>{verdict.source}</span><span aria-hidden="true">·</span>{/if}
				<span>{percent(entry.confidence)} confidence</span>
			</p>
		</div>
		<ReviewButtons {entry} {onreview} />
	</div>
</article>

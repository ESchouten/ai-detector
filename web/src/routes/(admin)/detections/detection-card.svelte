<script lang="ts">
	import { resolve } from '$app/paths';
	import { Badge } from '$lib/components/ui/badge';
	import { Button } from '$lib/components/ui/button';
	import { ThumbsUp, ThumbsDown, Undo2 } from '@lucide/svelte';
	import { toast } from 'svelte-sonner';
	import { reviewDetection } from '$lib/remote/detections.remote';
	import CardOverlay from '$lib/components/card-overlay.svelte';
	import CategoryBadge from '$lib/components/category-badge.svelte';
	import { STAGE_LABELS, type Detection } from '$lib/detections';
	let {
		entry,
		colorSeed,
		onreview
	}: { entry: Detection; colorSeed?: string; onreview: (entry: Detection) => void } = $props();
	let isPlaying = $state(false);
	let saving = $state(false);
	const time = $derived(formatTime(entry.start));
	const validationFailed = $derived(!entry.review && !!entry.validation_error);

	async function review(validated: boolean | null) {
		saving = true;
		try {
			const updated = await reviewDetection({
				type: entry.type,
				archiveStage: entry.archiveStage,
				timestamp: entry.timestamp,
				validated
			});
			onreview(updated);
			toast.success(
				validated === null
					? 'Manual review removed'
					: validated
						? 'Detection accepted'
						: 'Detection rejected'
			);
		} catch {
			toast.error('Could not save the review. Please try again.');
		} finally {
			saving = false;
		}
	}

	function formatTime(value: string) {
		const date = new Date(value);
		return Number.isNaN(date.getTime())
			? value
			: new Intl.DateTimeFormat(undefined, { timeStyle: 'short' }).format(date);
	}

	function getResource(resource: string) {
		return resolve(
			`/detections/${[entry.type, entry.archiveStage, entry.timestamp, resource].map(encodeURIComponent).join('/')}`
		);
	}
</script>

<div class="flex min-w-0 flex-col gap-2">
	<CardOverlay hide={isPlaying}>
		<video
			class="block h-auto w-full bg-black"
			controls
			preload="none"
			poster={getResource('best.jpg')}
			onplay={() => (isPlaying = true)}
			onpause={() => (isPlaying = false)}
			onended={() => (isPlaying = false)}
		>
			<source src={getResource('video.mp4')} type="video/mp4" />
			Your browser cannot play this video.
		</video>
		{#snippet overlay()}
			<div class="flex flex-wrap items-center gap-2">
				<CategoryBadge
					label={entry.type.charAt(0).toUpperCase() + entry.type.slice(1)}
					seed={colorSeed ?? entry.type}
				/>
				<Badge
					variant={validationFailed || entry.stage === 'rejected'
						? 'destructive'
						: entry.stage === 'approved'
							? 'success'
							: 'warning'}
					title={entry.review
						? `Manually reviewed via ${entry.review.source}`
						: 'Original validator result'}
				>
					{validationFailed ? 'Verification failed' : STAGE_LABELS[entry.stage]}{entry.review
						? ' · Reviewed'
						: ''}
				</Badge>
				<Badge variant="secondary"><time datetime={entry.start}>{time}</time></Badge>
				<Badge variant="secondary">{entry.duration.toFixed(1)}s</Badge>
				<Badge variant="secondary">Confidence: {(entry.confidence * 100).toFixed(1)}%</Badge>
			</div>
		{/snippet}
	</CardOverlay>
	<div class="flex flex-wrap items-center gap-2" aria-label="Review detection" aria-busy={saving}>
		<Button
			variant="outline"
			size="sm"
			disabled={saving || entry.review?.validated === true}
			onclick={() => review(true)}><ThumbsUp /> Accept</Button
		>
		<Button
			variant="outline"
			size="sm"
			disabled={saving || entry.review?.validated === false}
			onclick={() => review(false)}><ThumbsDown /> Reject</Button
		>
		{#if entry.review}
			<Button
				variant="ghost"
				size="sm"
				disabled={saving}
				onclick={() => review(null)}
				title="Restore the original validator result"><Undo2 /> Undo review</Button
			>
		{/if}
	</div>
</div>

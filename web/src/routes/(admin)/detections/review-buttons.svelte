<script lang="ts">
	import { ThumbsDown, ThumbsUp } from '@lucide/svelte';
	import { toast } from 'svelte-sonner';
	import { Button } from '$lib/components/ui/button';
	import { reviewDetection } from '$lib/remote/detections.remote';
	import type { Detection } from '$lib/detections';

	// A filled thumb is the recording's result, whoever decided it. Pressing a thumb records your
	// own review; pressing your own choice again removes it and restores the validator's result.
	let {
		entry,
		onreview,
		labels = false
	}: { entry: Detection; onreview: (entry: Detection) => void; labels?: boolean } = $props();
	let saving = $state(false);
	const confirmed = $derived(entry.stage === 'approved');
	const dismissed = $derived(entry.stage === 'rejected');
	const mine = $derived(entry.review !== null);

	async function review(validated: boolean) {
		const next = entry.review?.validated === validated ? null : validated;
		saving = true;
		try {
			onreview(
				await reviewDetection({
					type: entry.type,
					archiveStage: entry.archiveStage,
					timestamp: entry.timestamp,
					validated: next
				})
			);
			toast.success(
				next === null ? 'Review removed' : next ? 'Confirmed' : 'Marked as a false alarm'
			);
		} catch {
			toast.error('Could not save the review. Please try again.');
		} finally {
			saving = false;
		}
	}
</script>

<div
	class={['flex shrink-0 items-center', labels ? 'gap-2' : 'gap-1']}
	role="group"
	aria-label="Review"
	aria-busy={saving}
>
	<Button
		variant={labels ? 'outline' : 'ghost'}
		size={labels ? 'sm' : 'icon-sm'}
		class={confirmed
			? 'text-success-foreground hover:text-success-foreground' +
				(labels ? ' border-transparent bg-success hover:bg-success/80' : '')
			: ''}
		aria-pressed={confirmed}
		aria-label={confirmed
			? mine
				? 'Confirmed. Remove your review'
				: 'Confirmed by AI. Confirm it yourself'
			: 'Confirm: this is real'}
		title={confirmed && mine ? 'Remove your review' : 'Confirm: this is real'}
		disabled={saving}
		onclick={() => review(true)}
	>
		<ThumbsUp class={confirmed ? 'fill-current' : ''} aria-hidden="true" />{#if labels}{confirmed
				? 'Confirmed'
				: 'Confirm'}{/if}
	</Button>
	<Button
		variant={labels ? 'outline' : 'ghost'}
		size={labels ? 'sm' : 'icon-sm'}
		class={dismissed
			? 'text-danger-foreground hover:text-danger-foreground' +
				(labels ? ' border-transparent bg-danger hover:bg-danger/80' : '')
			: ''}
		aria-pressed={dismissed}
		aria-label={dismissed
			? mine
				? 'False alarm. Remove your review'
				: 'False alarm according to AI. Mark it yourself'
			: 'False alarm'}
		title={dismissed && mine ? 'Remove your review' : 'False alarm'}
		disabled={saving}
		onclick={() => review(false)}
	>
		<ThumbsDown class={dismissed ? 'fill-current' : ''} aria-hidden="true" />{#if labels}False alarm{/if}
	</Button>
</div>

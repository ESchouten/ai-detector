<script lang="ts">
	import { resolve } from '$app/paths';
	import { Badge } from '$lib/components/ui/badge';
	import CardOverlay from '$lib/components/card-overlay.svelte';
	import type { Detection } from '$lib/detections';

	const stageLabels = {
		approved: 'Approved',
		rejected: 'Rejected',
		unvalidated: 'Unvalidated'
	} as const;
	let { entry }: { entry: Detection } = $props();
	let isPlaying = $state(false);
	const time = $derived(formatTime(entry.start));

	function formatTime(value: string) {
		const date = new Date(value);
		return Number.isNaN(date.getTime())
			? value
			: new Intl.DateTimeFormat(undefined, { timeStyle: 'short' }).format(date);
	}

	function getResource(resource: string) {
		return resolve(
			`/detections/${[entry.type, entry.stage, entry.timestamp, resource].map(encodeURIComponent).join('/')}`
		);
	}
</script>

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
			<Badge variant="secondary">{entry.type.charAt(0).toUpperCase() + entry.type.slice(1)}</Badge>
			<Badge
				variant={entry.validation_error || entry.stage === 'rejected' ? 'destructive' : 'secondary'}
			>
				{entry.validation_error ? 'Verification failed' : stageLabels[entry.stage]}
			</Badge>
			<Badge variant="secondary"><time datetime={entry.start}>{time}</time></Badge>
			<Badge variant="secondary">{entry.duration.toFixed(1)}s</Badge>
			<Badge variant="secondary">Confidence: {(entry.confidence * 100).toFixed(1)}%</Badge>
		</div>
	{/snippet}
</CardOverlay>

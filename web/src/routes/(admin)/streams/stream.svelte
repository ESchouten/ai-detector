<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import CardOverlay from '$lib/components/card-overlay.svelte';
	import { Badge } from '$lib/components/ui/badge';
	import { Spinner } from '$lib/components/ui/spinner';

	type Props = {
		label: string;
		source: string;
		showLoading?: boolean;
		hideOverlay?: boolean;
		disableLink?: boolean;
	};

	let {
		label,
		source,
		showLoading = false,
		hideOverlay = false,
		disableLink = false
	}: Props = $props();

	let imageReady = $state(false);
	let unavailable = $state(false);

	const streamUrl = $derived(resolve(`/streams/${encodeURIComponent(source)}`));
	const loading = $derived(!imageReady && !unavailable);

	function handleLoad() {
		imageReady = true;
		unavailable = false;
	}

	function handleError() {
		imageReady = false;
		unavailable = true;
	}

	function preview(node: HTMLImageElement) {
		imageReady = false;
		unavailable = false;
		return {
			destroy() {
				node.src = 'data:,';
			}
		};
	}
</script>

{#if showLoading && loading}
	<Spinner class="size-8" />
{/if}
<CardOverlay overlay={hideOverlay ? undefined : overlay}>
	<button
		class="relative block aspect-video w-full cursor-pointer bg-black"
		onclick={disableLink
			? undefined
			: () =>
					goto(
						resolve(
							`/streams/add?source=${encodeURIComponent(source)}&label=${encodeURIComponent(label)}`
						)
					)}
	>
		{#key streamUrl}
			<img
				use:preview
				src={streamUrl}
				alt={label}
				class="block h-full w-full object-contain"
				onload={handleLoad}
				onerror={handleError}
			/>
		{/key}

		{#if unavailable}
			<div
				class="absolute inset-0 flex items-center justify-center px-4 text-center text-xs text-white/70"
			>
				Live stream unavailable.
			</div>
		{:else if loading && !showLoading}
			<div
				class="absolute inset-0 flex items-center justify-center px-4 text-center text-xs text-white/60"
			>
				Loading...
			</div>
		{/if}
	</button>
</CardOverlay>

{#snippet overlay()}
	<div class="flex flex-wrap items-center gap-2 text-xs">
		<Badge variant="secondary" class="bg-black/50 text-white">{label}</Badge>
		<Badge variant="secondary" class="bg-black/50 text-white">{source}</Badge>
	</div>
{/snippet}

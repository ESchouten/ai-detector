<script lang="ts">
	import { page } from '$app/state';
	import DetectorEditor from './detector-editor.svelte';
	import * as Alert from '$lib/components/ui/alert';
	import { getDetector } from '$lib/remote/detector.remote';

	const label = $derived(page.url.searchParams.get('label') ?? '');
	const saved = $derived(label ? await getDetector({ label }) : undefined);
	const setupMode = $derived(page.url.searchParams.get('setup') === '1');
</script>

<svelte:head><title>Detector settings · AI Detector</title></svelte:head>

{#if label && !saved}
	<Alert.Root variant="destructive">
		<Alert.Title>Detector not found</Alert.Title>
		<Alert.Description
			>This detector may have been removed. Return to the detector list to select another.</Alert.Description
		>
	</Alert.Root>
{:else}
	{#key label}
		<DetectorEditor originalLabel={label} initial={saved?.detector} {setupMode} />
	{/key}
{/if}

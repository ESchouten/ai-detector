<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import * as Alert from '$lib/components/ui/alert';
	import DetectorEditor from '$lib/components/detector-editor.svelte';
	import PageHeader from '$lib/components/page-header.svelte';
	import { getDetectors } from '$lib/remote/detector.remote';

	const label = $derived(page.url.searchParams.get('label') ?? '');
	const detectors = $derived(await getDetectors());
	const saved = $derived(detectors.find((item) => item.meta.label === label));
	const back = { href: resolve('/detectors'), label: 'Detectors' };
	const done = async () => void (await goto(resolve('/detectors')));
</script>

<section class="page-narrow">
	{#if !saved}
		<PageHeader {back} title="Detector not found" />
		<Alert.Root variant="destructive">
			<Alert.Title>Detector not found</Alert.Title>
			<Alert.Description>This detector may have been removed or renamed.</Alert.Description>
		</Alert.Root>
	{:else}
		<PageHeader {back} title={saved.meta.label} />
		{#key label}
			<DetectorEditor
				originalLabel={label}
				initial={saved.detector}
				initialPreset={saved.meta.preset}
				initialAutoUpdate={saved.meta.autoUpdate !== false}
				initialConnection={saved.meta.llmConnection}
				onDone={done}
				onCancel={done}
			/>
		{/key}
	{/if}
</section>

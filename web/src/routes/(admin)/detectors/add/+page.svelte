<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
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
	{#if label && !saved}
		<PageHeader
			{back}
			title="Detector not found"
			description="It may have been removed or renamed."
		/>
	{:else}
		<PageHeader {back} title={saved ? saved.meta.label : 'Add a detector'} />
		{#key label}
			<DetectorEditor initial={saved} onDone={done} onCancel={done} />
		{/key}
	{/if}
</section>

<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import DetectorEditor from '$lib/components/detector-editor.svelte';
	import PageHeader from '$lib/components/page-header.svelte';

	const detectors = async () => void (await goto(resolve('/detectors')));
</script>

<svelte:head><title>Add detector · AI Detector</title></svelte:head>
<section class="page-narrow">
	<PageHeader back={{ href: resolve('/detectors'), label: 'Detectors' }} title="Add a detector" />
	<DetectorEditor originalLabel="" onDone={detectors} onCancel={detectors} />
</section>

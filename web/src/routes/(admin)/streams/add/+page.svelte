<script lang="ts">
	import { page } from '$app/state';
	import StreamEditor from './stream-editor.svelte';
	const source = $derived(page.url.searchParams.get('source') ?? '');
	const label = $derived(page.url.searchParams.get('label') ?? '');
	const setupMode = $derived(page.url.searchParams.get('setup') === '1');
</script>

<svelte:head><title>Camera settings · AI Detector</title></svelte:head>

{#key source}
	<StreamEditor originalSource={source} initialLabel={label} {setupMode} />
{/key}

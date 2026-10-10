<script lang="ts">
	import { page } from '$app/state';
	import { getLlmConnections, canTestLlm } from '$lib/remote/llm.remote';
	import LlmConnectionEditor from '$lib/components/llm-connection-editor.svelte';
	import PageHeader from '$lib/components/page-header.svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import * as Alert from '$lib/components/ui/alert';
	const label = $derived(page.url.searchParams.get('label') ?? '');
	const [connections, canTest] = await Promise.all([getLlmConnections(), canTestLlm()]);
	const initial = $derived(connections.find((connection) => connection.label === label));
	const back = { href: resolve('/validator'), label: 'Validator' };
</script>

<section class="page-narrow">
	{#if label && !initial}
		<PageHeader {back} title="Connection not found" />
		<Alert.Root variant="destructive">
			<Alert.Title>Connection not found</Alert.Title>
			<Alert.Description>Return to Validator and select an existing connection.</Alert.Description>
		</Alert.Root>
	{:else}
		<PageHeader
			{back}
			title={initial ? initial.label : 'Connect validator'}
			description="Connect Google Gemini to check detections before alerts are sent."
		/>
		{#key label}
			<LlmConnectionEditor
				{initial}
				{canTest}
				onSaved={() => goto(resolve('/validator'))}
				onCancel={() => void goto(resolve('/validator'))}
			/>
		{/key}
	{/if}
</section>

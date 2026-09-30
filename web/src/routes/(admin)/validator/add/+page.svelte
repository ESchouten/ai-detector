<script lang="ts">
	import { page } from '$app/state';
	import { getLlmConnections, canTestLlm } from '$lib/remote/llm.remote';
	import LlmConnectionEditor from '$lib/components/llm-connection-editor.svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import * as Alert from '$lib/components/ui/alert';
	const label = $derived(page.url.searchParams.get('label') ?? '');
	const [connections, canTest] = await Promise.all([getLlmConnections(), canTestLlm()]);
	const initial = $derived(connections.find((connection) => connection.label === label));
</script>

<svelte:head><title>AI connection · AI Detector</title></svelte:head>
{#if label && !initial}
	<Alert.Root variant="destructive"
		><Alert.Title>Connection not found</Alert.Title><Alert.Description
			>Return to Validator and select an existing connection.</Alert.Description
		></Alert.Root
	>
{:else}
	<section class="settings-page max-w-2xl">
		<header class="flex flex-col gap-2">
			<h1 class="settings-heading">{initial ? 'Edit AI connection' : 'Add AI connection'}</h1>
			<p class="settings-description">
				Connect once, then choose this connection in your detectors.
			</p>
		</header>
		{#key label}<LlmConnectionEditor
				{initial}
				{canTest}
				onSaved={() => goto(resolve('/validator'))}
				onCancel={() => void goto(resolve('/validator'))}
			/>{/key}
	</section>
{/if}

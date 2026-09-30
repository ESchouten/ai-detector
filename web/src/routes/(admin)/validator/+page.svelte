<script lang="ts">
	import { resolve } from '$app/paths';
	import { Plus } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import * as Empty from '$lib/components/ui/empty';
	import * as Table from '$lib/components/ui/table';
	import { getLlmConnections } from '$lib/remote/llm.remote';
	import { getDetectors } from '$lib/remote/detector.remote';
	const [connections, detectors] = await Promise.all([getLlmConnections(), getDetectors()]);
</script>

<svelte:head><title>Validator · AI Detector</title></svelte:head>
<section class="settings-page max-w-4xl">
	<header class="flex flex-col gap-2">
		<div class="flex flex-wrap items-center justify-between gap-3">
			<h1 class="settings-heading">Validator</h1>
			{#if connections.length}<Button href={resolve('/validator/add')}
					><Plus data-icon="inline-start" />Add connection</Button
				>{/if}
		</div>
		<p class="settings-description">
			Connect an AI service once. Each detector chooses its own question.
		</p>
	</header>
	{#if connections.length}
		<Table.Root>
			<Table.Header
				><Table.Row
					><Table.Head>Connection</Table.Head><Table.Head>Used by</Table.Head><Table.Head
						><span class="sr-only">Actions</span></Table.Head
					></Table.Row
				></Table.Header
			>
			<Table.Body>
				{#each connections as connection (connection.label)}
					{@const assigned = detectors.filter(
						({ meta }) => meta.llmConnection === connection.label
					)}
					<Table.Row>
						<Table.Cell class="whitespace-normal"
							><p class="font-medium">{connection.label}</p>
							<p class="text-sm break-all text-muted-foreground">{connection.model}</p></Table.Cell
						>
						<Table.Cell class="whitespace-normal"
							>{assigned.map(({ meta }) => meta.label).join(', ') || 'Not assigned yet'}</Table.Cell
						>
						<Table.Cell class="text-right"
							><Button
								variant="outline"
								size="sm"
								href={resolve(`/validator/add?label=${encodeURIComponent(connection.label)}`)}
								aria-label={`Edit ${connection.label}`}>Edit</Button
							></Table.Cell
						>
					</Table.Row>
				{/each}
			</Table.Body>
		</Table.Root>
	{:else}
		<Empty.Root
			><Empty.Header
				><Empty.Title>No AI connections</Empty.Title><Empty.Description
					>Optionally ask an AI model to check detections before alerts are sent. Monitoring also
					works without this.</Empty.Description
				></Empty.Header
			><Empty.Content
				><Button href={resolve('/validator/add')}>Add AI connection</Button></Empty.Content
			></Empty.Root
		>
	{/if}
</section>

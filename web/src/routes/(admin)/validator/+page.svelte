<script lang="ts">
	import { resolve } from '$app/paths';
	import { Plus, Sparkles } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import * as Empty from '$lib/components/ui/empty';
	import LinkRows from '$lib/components/link-rows.svelte';
	import PageHeader from '$lib/components/page-header.svelte';
	import { getLlmConnections } from '$lib/remote/llm.remote';
	import { getDetectors } from '$lib/remote/detector.remote';
	const [connections, detectors] = $derived(
		await Promise.all([getLlmConnections(), getDetectors()])
	);
</script>

<section class="page-narrow">
	<PageHeader
		back={{ href: resolve('/settings'), label: 'Settings' }}
		title="Validator"
		description="An AI model looks at each clip before an alert is sent and filters out false alarms. Your presets supply the question it answers."
	>
		{#snippet actions()}
			{#if connections.length}
				<Button href={resolve('/validator/add')}>
					<Plus data-icon="inline-start" aria-hidden="true" />Add connection
				</Button>
			{/if}
		{/snippet}
	</PageHeader>
	{#if connections.length}
		<LinkRows
			items={connections.map((connection) => {
				const assigned = detectors.filter(({ meta }) => meta.llmConnection === connection.label);
				return {
					title: connection.label,
					href: resolve(`/validator/add?label=${encodeURIComponent(connection.label)}`),
					icon: Sparkles,
					description: assigned.length
						? `Checks ${assigned.map(({ meta }) => meta.label).join(', ')}`
						: 'Not used by a detector yet'
				};
			})}
		/>
		<p class="text-sm text-muted-foreground">
			Turn the validator on or off for each detector under
			<a
				href={resolve('/detectors')}
				class="font-medium text-foreground underline underline-offset-4">Detectors</a
			>.
		</p>
	{:else}
		<Empty.Root class="border border-dashed">
			<Empty.Header>
				<Empty.Media variant="icon"><Sparkles aria-hidden="true" /></Empty.Media>
				<Empty.Title>No validator connected</Empty.Title>
				<Empty.Description>
					Optional. Without it, every detection is recorded and alerted as it is.
				</Empty.Description>
			</Empty.Header>
			<Empty.Content>
				<Button href={resolve('/validator/add')}>Connect Google Gemini</Button>
			</Empty.Content>
		</Empty.Root>
	{/if}
</section>

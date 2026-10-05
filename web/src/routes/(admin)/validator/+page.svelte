<script lang="ts">
	import { resolve } from '$app/paths';
	import { ChevronRight, Plus, Sparkles } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import * as Empty from '$lib/components/ui/empty';
	import PageHeader from '$lib/components/page-header.svelte';
	import { getLlmConnections } from '$lib/remote/llm.remote';
	import { getDetectors } from '$lib/remote/detector.remote';
	const [connections, detectors] = $derived(
		await Promise.all([getLlmConnections(), getDetectors()])
	);
</script>

<svelte:head><title>Validator · AI Detector</title></svelte:head>
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
		<ul class="panel divide-y overflow-hidden">
			{#each connections as connection (connection.label)}
				{@const assigned = detectors.filter(({ meta }) => meta.llmConnection === connection.label)}
				<li>
					<a
						href={resolve(`/validator/add?label=${encodeURIComponent(connection.label)}`)}
						aria-label={`Edit ${connection.label}`}
						class="group flex items-center gap-4 px-4 py-3.5 transition-colors outline-none hover:bg-accent/60 focus-visible:bg-accent"
					>
						<span
							class="flex size-9 shrink-0 items-center justify-center rounded-lg bg-secondary text-secondary-foreground"
						>
							<Sparkles class="size-[1.125rem]" aria-hidden="true" />
						</span>
						<span class="flex min-w-0 flex-1 flex-col">
							<span class="text-sm font-medium">{connection.label}</span>
							<span class="text-sm text-muted-foreground">
								{assigned.length
									? `Checks ${assigned.map(({ meta }) => meta.label).join(', ')}`
									: 'Not used by a detector yet'}
							</span>
						</span>
						<ChevronRight
							class="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5"
							aria-hidden="true"
						/>
					</a>
				</li>
			{/each}
		</ul>
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

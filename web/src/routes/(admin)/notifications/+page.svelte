<script lang="ts">
	import { resolve } from '$app/paths';
	import { Bell, ChevronRight, Plus } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import * as Empty from '$lib/components/ui/empty';
	import PageHeader from '$lib/components/page-header.svelte';
	import { getTelegrams } from '$lib/remote/exporter.remote';
	import { getDetectors } from '$lib/remote/detector.remote';
	import { recipientDetectorLabels } from '$lib/alert-recipients';
	const [detectors, telegrams] = $derived(await Promise.all([getDetectors(), getTelegrams()]));
</script>

<svelte:head><title>Alerts · AI Detector</title></svelte:head>

<section class="page-narrow">
	<PageHeader
		back={{ href: resolve('/settings'), label: 'Settings' }}
		title="Alerts"
		description="When a detector sees something, the clip is sent to these people in Telegram. They can confirm it or mark it as a false alarm right there."
	>
		{#snippet actions()}
			{#if telegrams.length}
				<Button href={resolve('/notifications/add')}>
					<Plus data-icon="inline-start" aria-hidden="true" />Add recipient
				</Button>
			{/if}
		{/snippet}
	</PageHeader>
	{#if telegrams.length}
		<ul class="panel divide-y overflow-hidden">
			{#each telegrams as telegram (telegram.label)}
				{@const assigned = recipientDetectorLabels(detectors, telegram)}
				<li>
					<a
						href={resolve(`/notifications/add?label=${encodeURIComponent(telegram.label)}`)}
						aria-label={`Edit recipient ${telegram.label}`}
						class="group flex items-center gap-4 px-4 py-3.5 transition-colors outline-none hover:bg-accent/60 focus-visible:bg-accent"
					>
						<span
							class="flex size-9 shrink-0 items-center justify-center rounded-lg bg-secondary text-secondary-foreground"
						>
							<Bell class="size-[1.125rem]" aria-hidden="true" />
						</span>
						<span class="flex min-w-0 flex-1 flex-col">
							<span class="text-sm font-medium">{telegram.label}</span>
							<span class="text-sm text-muted-foreground">
								{assigned.length
									? `Alerts from ${assigned.join(', ')}`
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
	{:else}
		<Empty.Root class="border border-dashed">
			<Empty.Header>
				<Empty.Media variant="icon"><Bell aria-hidden="true" /></Empty.Media>
				<Empty.Title>No phone alerts yet</Empty.Title>
				<Empty.Description>
					Connect Telegram to get each event on your phone. Monitoring and recording also work
					without alerts.
				</Empty.Description>
			</Empty.Header>
			<Empty.Content>
				<Button href={resolve('/notifications/add')}>Connect your phone</Button>
			</Empty.Content>
		</Empty.Root>
	{/if}
</section>

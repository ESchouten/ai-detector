<script lang="ts">
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
	import * as Card from '$lib/components/ui/card';
	import * as Empty from '$lib/components/ui/empty';
	import * as Table from '$lib/components/ui/table';
	import { getTelegrams } from '$lib/remote/exporter.remote';
	import { Plus } from '@lucide/svelte';
	import { getDetectors } from '$lib/remote/detector.remote';
	import { recipientDetectorLabels } from '$lib/alert-recipients';
	const [detectors, telegrams] = await Promise.all([getDetectors(), getTelegrams()]);
</script>

<svelte:head><title>Alerts · AI Detector</title></svelte:head>

<section class="settings-page max-w-4xl">
	<header class="flex flex-col gap-2">
		<div class="flex flex-wrap items-center justify-between gap-3">
			<h1 class="settings-heading">Alerts</h1>
			{#if telegrams.length}<Button href={resolve('/notifications/add')}
					><Plus data-icon="inline-start" /> Connect alerts</Button
				>{/if}
		</div>
		<p class="settings-description">
			Choose who receives Telegram alerts and which detectors send them.
		</p>
	</header>
	<div>
		<Card.Root class="min-w-0">
			<Card.Header
				><Card.Title>Recipients</Card.Title><Card.Description
					>Use one saved recipient for as many detectors as you need.</Card.Description
				></Card.Header
			>
			<Card.Content>
				{#if telegrams.length}
					<Table.Root>
						<Table.Header
							><Table.Row
								><Table.Head>Recipient</Table.Head><Table.Head class="whitespace-normal"
									>Detectors sending alerts</Table.Head
								><Table.Head><span class="sr-only">Actions</span></Table.Head></Table.Row
							></Table.Header
						>
						<Table.Body>
							{#each telegrams as telegram (telegram.label)}
								{@const assignedDetectors = recipientDetectorLabels(detectors, telegram)}
								<Table.Row>
									<Table.Cell class="font-medium">{telegram.label}</Table.Cell>
									<Table.Cell class="whitespace-normal"
										>{#if assignedDetectors.length}<ul class="flex flex-col gap-1">
												{#each assignedDetectors as label (label)}<li>{label}</li>{/each}
											</ul>{:else}<span class="text-muted-foreground"
												>Not enabled for any detector</span
											>{/if}</Table.Cell
									>
									<Table.Cell class="text-right"
										><Button
											href={resolve(
												`/notifications/add?label=${encodeURIComponent(telegram.label)}`
											)}
											variant="outline"
											size="sm"
											aria-label={`Edit recipient ${telegram.label}`}>Edit</Button
										></Table.Cell
									>
								</Table.Row>
							{/each}
						</Table.Body>
					</Table.Root>
				{:else}
					<Empty.Root
						><Empty.Header
							><Empty.Title>No alerts connected</Empty.Title><Empty.Description
								>Connect Telegram to receive events on your phone. Monitoring and local recording
								also work without alerts.</Empty.Description
							></Empty.Header
						><Empty.Content
							><Button href={resolve('/notifications/add')}>Connect your phone</Button
							></Empty.Content
						></Empty.Root
					>
				{/if}
			</Card.Content>
		</Card.Root>
	</div>
</section>

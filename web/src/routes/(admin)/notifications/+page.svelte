<script lang="ts">
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
	import * as Card from '$lib/components/ui/card';
	import * as Empty from '$lib/components/ui/empty';
	import * as Table from '$lib/components/ui/table';
	import { getTelegrams } from '$lib/remote/exporter.remote';
	import { Plus } from '@lucide/svelte';
	import { getCameras } from '$lib/remote/stream.remote';
	const cameras = $derived(await getCameras());
	const telegrams = $derived(await getTelegrams());
</script>

<svelte:head><title>Alerts · AI Detector</title></svelte:head>

<section class="settings-page">
	<header class="flex flex-col gap-2">
		<div class="flex flex-wrap items-center justify-between gap-3">
			<h1 class="settings-heading">Alerts</h1>
			<Button href={resolve('/notifications/add')}
				><Plus data-icon="inline-start" /> Connect alerts</Button
			>
		</div>
		<p class="settings-description">
			Choose who receives Telegram alerts and which cameras send them.
		</p>
	</header>
	<div class="settings-layout">
		<Card.Root class="min-w-0">
			<Card.Header
				><Card.Title>Recipients</Card.Title><Card.Description
					>Use one saved recipient for as many monitored cameras as you need.</Card.Description
				></Card.Header
			>
			<Card.Content>
				{#if telegrams.length}
					<Table.Root>
						<Table.Header
							><Table.Row
								><Table.Head>Recipient</Table.Head><Table.Head>Cameras sending alerts</Table.Head
								><Table.Head><span class="sr-only">Actions</span></Table.Head></Table.Row
							></Table.Header
						>
						<Table.Body>
							{#each telegrams as telegram (telegram.label)}
								{@const assignedCameras = cameras.filter((camera) =>
									camera.alerts.includes(telegram.label)
								)}
								<Table.Row>
									<Table.Cell class="font-medium">{telegram.label}</Table.Cell>
									<Table.Cell
										>{#if assignedCameras.length}<ul class="flex flex-col gap-1">
												{#each assignedCameras as camera (camera.id)}<li>{camera.label}</li>{/each}
											</ul>{:else}<span class="text-muted-foreground"
												>Not enabled for any camera</span
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
		<aside class="settings-aside">
			<div class="flex flex-col gap-2">
				<h2 class="text-sm font-semibold">Connect once, reuse later</h2>
				<p class="text-sm text-muted-foreground">
					You do not need a new Telegram bot for each camera. Edit a recipient to add more cameras.
				</p>
			</div>
			<div class="flex flex-col gap-2">
				<h2 class="text-sm font-semibold">Alerts are optional</h2>
				<p class="text-sm text-muted-foreground">
					Removing a recipient stops its alerts. Camera monitoring and saved recordings stay in
					place.
				</p>
			</div>
			<Button href={resolve('/streams')} variant="outline" class="self-start">Open cameras</Button>
		</aside>
	</div>
</section>

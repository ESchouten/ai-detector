<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import * as Table from '$lib/components/ui/table';
	import { getTelegrams } from '$lib/remote/exporter.remote';
	import { Plus } from '@lucide/svelte';
	import { getCameras } from '$lib/remote/stream.remote';
	const cameras = $derived(await getCameras());
	const telegrams = $derived(await getTelegrams());
</script>

<svelte:head><title>Alerts · AI Detector</title></svelte:head>

<section class="flex flex-col gap-6">
	<header class="flex flex-col gap-1">
		<div class="flex flex-wrap items-center justify-between gap-3">
			<h1 class="text-2xl font-semibold tracking-tight">Alerts</h1>
			<Button href="/notifications/add" variant="outline">
				<Plus /> Connect alerts</Button
			>
		</div>
		<p class="text-sm text-muted-foreground">See which cameras send alerts to each recipient.</p>
	</header>
	<Table.Root>
		<Table.Header>
			<Table.Row>
				<Table.Head>Name</Table.Head>
				<Table.Head>Monitored cameras</Table.Head>
				<Table.Head>
					<span class="sr-only">Actions</span>
				</Table.Head>
			</Table.Row>
		</Table.Header>
		<Table.Body>
			{#each telegrams as telegram (telegram.label)}
				<Table.Row>
					<Table.Cell>{telegram.label}</Table.Cell>
					<Table.Cell
						>{cameras
							.filter((camera) => camera.alerts.includes(telegram.label))
							.map((camera) => camera.label)
							.join(', ') || 'Not enabled for any camera'}</Table.Cell
					>
					<Table.Cell>
						<Button
							href={`/notifications/add?label=${encodeURIComponent(telegram.label)}`}
							variant="outline"
							size="sm"
							aria-label={`Edit ${telegram.label}`}>Edit</Button
						>
					</Table.Cell>
				</Table.Row>
			{:else}
				<Table.Row>
					<Table.Cell colspan={3}
						>No alerts connected. Monitoring and local recording work without alerts.</Table.Cell
					>
				</Table.Row>
			{/each}
		</Table.Body>
	</Table.Root>
</section>

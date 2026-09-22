<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import * as Table from '$lib/components/ui/table';
	import { getTelegrams } from '$lib/remote/exporter.remote';
	import { Plus } from '@lucide/svelte';
	const telegrams = $derived(await getTelegrams());
</script>

<svelte:head><title>Notifications · AI Detector</title></svelte:head>

<section class="flex flex-col gap-6">
	<header class="flex flex-col gap-1">
		<div class="flex flex-wrap items-center justify-between gap-3">
			<h1 class="text-2xl font-semibold tracking-tight">Notifications</h1>
			<Button href="/notifications/add" variant="outline">
				<Plus /> Add Telegram</Button
			>
		</div>
		<p class="text-sm text-muted-foreground">Configure notification channels for detections.</p>
	</header>
	<Table.Root>
		<Table.Header>
			<Table.Row>
				<Table.Head>Name</Table.Head>
				<Table.Head>Chat</Table.Head>
				<Table.Head>
					<span class="sr-only">Actions</span>
				</Table.Head>
			</Table.Row>
		</Table.Header>
		<Table.Body>
			{#each telegrams as telegram (telegram.label)}
				<Table.Row>
					<Table.Cell>{telegram.label}</Table.Cell>
					<Table.Cell>{telegram.chat}</Table.Cell>
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
						>No notification channels yet. Add Telegram to receive alerts.</Table.Cell
					>
				</Table.Row>
			{/each}
		</Table.Body>
	</Table.Root>
</section>

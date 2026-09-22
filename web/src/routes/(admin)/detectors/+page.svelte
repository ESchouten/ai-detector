<script lang="ts">
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
	import * as Table from '$lib/components/ui/table';
	import { getDetectors } from '$lib/remote/detector.remote';
	import { Plus } from '@lucide/svelte';

	const detectors = $derived(await getDetectors());
</script>

<svelte:head><title>Detectors · AI Detector</title></svelte:head>

<section class="space-y-6">
	<header class="space-y-1">
		<div class="flex items-center justify-between">
			<h1 class="text-2xl font-semibold tracking-tight">Detectors</h1>
			<Button href={resolve('/detectors/add')} variant="outline"><Plus /> Add Detector</Button>
		</div>
		<p class="text-sm text-muted-foreground">Configure detectors.</p>
	</header>

	<Table.Root>
		<Table.Header>
			<Table.Row>
				<Table.Head>Name</Table.Head>
				<Table.Head>Model</Table.Head>
				<Table.Head>Streams</Table.Head>
				<Table.Head><span class="sr-only">Actions</span></Table.Head>
			</Table.Row>
		</Table.Header>
		<Table.Body>
			{#each detectors as { detector, meta } (meta.label)}
				<Table.Row>
					<Table.Cell>{meta.label}</Table.Cell>
					<Table.Cell>{detector.yolo?.model?.split('/').pop() || 'Snapshots'}</Table.Cell>
					<Table.Cell>{detector.detection.source.length} stream(s)</Table.Cell>
					<Table.Cell>
						<Button
							variant="ghost"
							href={resolve(`/detectors/add?label=${encodeURIComponent(meta.label)}`)}
							aria-label={`Edit ${meta.label}`}>Edit</Button
						>
					</Table.Cell>
				</Table.Row>
			{:else}
				<Table.Row
					><Table.Cell colspan={4} class="text-muted-foreground"
						>No detectors configured. Add a detector to get started.</Table.Cell
					></Table.Row
				>
			{/each}
		</Table.Body>
	</Table.Root>
</section>

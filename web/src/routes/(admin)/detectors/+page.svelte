<script lang="ts">
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
	import * as Card from '$lib/components/ui/card';
	import * as Empty from '$lib/components/ui/empty';
	import * as Table from '$lib/components/ui/table';
	import { getDetectors } from '$lib/remote/detector.remote';
	import { getCameras } from '$lib/remote/stream.remote';
	import { Plus } from '@lucide/svelte';

	const detectors = $derived(await getDetectors());
	const cameras = $derived(await getCameras());
</script>

<svelte:head><title>Detectors · AI Detector</title></svelte:head>

<section class="settings-page">
	<header class="flex flex-col gap-2">
		<div class="flex flex-wrap items-center justify-between gap-3">
			<h1 class="settings-heading">Detectors</h1>
			{#if detectors.length}<Button href={resolve('/detectors/add')}
					><Plus data-icon="inline-start" /> Add detector</Button
				>{/if}
		</div>
		<p class="settings-description">
			Choose what each camera detects and how its events are delivered.
		</p>
	</header>
	<div class="max-w-4xl">
		<Card.Root class="min-w-0">
			<Card.Header
				><Card.Title>Your detectors</Card.Title><Card.Description
					>Choose a detector to change its settings or cameras.</Card.Description
				></Card.Header
			>
			<Card.Content>
				{#if detectors.length}
					<Table.Root>
						<Table.Header
							><Table.Row
								><Table.Head>Detector</Table.Head><Table.Head>Cameras</Table.Head><Table.Head
									><span class="sr-only">Actions</span></Table.Head
								></Table.Row
							></Table.Header
						>
						<Table.Body>
							{#each detectors as { detector, meta } (meta.label)}
								<Table.Row>
									<Table.Cell class="font-medium">{meta.label}</Table.Cell>
									<Table.Cell
										><ul class="flex flex-col gap-1">
											{#each detector.detection.source as source (source)}<li>
													{cameras.find((camera) => camera.source === source)?.label ??
														'Custom source'}
												</li>{/each}
										</ul></Table.Cell
									>
									<Table.Cell class="text-right"
										><Button
											variant="outline"
											size="sm"
											href={resolve(`/detectors/add?label=${encodeURIComponent(meta.label)}`)}
											aria-label={`Edit detector ${meta.label}`}>Edit</Button
										></Table.Cell
									>
								</Table.Row>
							{/each}
						</Table.Body>
					</Table.Root>
				{:else}
					<Empty.Root>
						<Empty.Header
							><Empty.Title>No detectors yet</Empty.Title><Empty.Description
								>Add your cameras first, then choose a preset and select which cameras it watches.</Empty.Description
							></Empty.Header
						>
						<Empty.Content
							><Button href={resolve(cameras.length ? '/detectors/add' : '/setup?step=cameras')}
								>{cameras.length ? 'Add detector' : 'Add a camera'}</Button
							></Empty.Content
						>
					</Empty.Root>
				{/if}
			</Card.Content>
		</Card.Root>
	</div>
</section>

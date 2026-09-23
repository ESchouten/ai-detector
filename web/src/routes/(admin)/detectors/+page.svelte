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

<svelte:head><title>Monitoring rules · AI Detector</title></svelte:head>

<section class="settings-page">
	<header class="flex flex-col gap-2">
		<div class="flex flex-wrap items-center justify-between gap-3">
			<h1 class="settings-heading">Monitoring rules</h1>
			<Button href={resolve('/detectors/add')}><Plus data-icon="inline-start" /> Add rule</Button>
		</div>
		<p class="settings-description">
			Choose what each camera detects and how its events are delivered.
		</p>
	</header>
	<div class="settings-layout">
		<Card.Root class="min-w-0">
			<Card.Header
				><Card.Title>Your rules</Card.Title><Card.Description
					>Each rule has its own model, detection settings and delivery options.</Card.Description
				></Card.Header
			>
			<Card.Content>
				{#if detectors.length}
					<Table.Root>
						<Table.Header
							><Table.Row
								><Table.Head>Rule</Table.Head><Table.Head>Cameras</Table.Head><Table.Head
									>Model</Table.Head
								><Table.Head><span class="sr-only">Actions</span></Table.Head></Table.Row
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
									<Table.Cell
										class="max-w-64 truncate"
										title={detector.yolo?.model?.split(/[\\/]/).pop()}
										>{detector.yolo?.model?.split(/[\\/]/).pop() || 'Snapshots'}</Table.Cell
									>
									<Table.Cell class="text-right"
										><Button
											variant="outline"
											size="sm"
											href={resolve(`/detectors/add?label=${encodeURIComponent(meta.label)}`)}
											aria-label={`Edit rule ${meta.label}`}>Edit</Button
										></Table.Cell
									>
								</Table.Row>
							{/each}
						</Table.Body>
					</Table.Root>
				{:else}
					<Empty.Root>
						<Empty.Header
							><Empty.Title>No monitoring rules yet</Empty.Title><Empty.Description
								>Set up a camera to start with a preset, or create a custom rule here.</Empty.Description
							></Empty.Header
						>
						<Empty.Content
							><Button href={resolve('/setup')}>Set up a camera</Button><Button
								href={resolve('/detectors/add')}
								variant="outline">Create a custom rule</Button
							></Empty.Content
						>
					</Empty.Root>
				{/if}
			</Card.Content>
		</Card.Root>
		<aside class="settings-aside">
			<div class="flex flex-col gap-2">
				<h2 class="text-sm font-semibold">Cameras and rules</h2>
				<p class="text-sm text-muted-foreground">
					A rule can watch several cameras. A camera can also use several rules, each with a
					different model or preset.
				</p>
			</div>
			<div class="flex flex-col gap-2">
				<h2 class="text-sm font-semibold">Looking for camera setup?</h2>
				<p class="text-sm text-muted-foreground">
					Manage camera connections and check the live picture on the Cameras page.
				</p>
				<Button href={resolve('/streams')} variant="outline" class="self-start">Open cameras</Button
				>
			</div>
		</aside>
	</div>
</section>

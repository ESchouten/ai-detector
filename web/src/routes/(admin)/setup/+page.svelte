<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { Button } from '$lib/components/ui/button';
	import { Badge } from '$lib/components/ui/badge';
	import * as Empty from '$lib/components/ui/empty';
	import { ArrowRight, Plus } from '@lucide/svelte';
	import CameraPicture from '$lib/components/camera-picture.svelte';
	import SetupReview from '$lib/components/setup-review.svelte';
	import DetectorRuntime from '$lib/components/detector-runtime.svelte';
	import SetupSteps from '$lib/components/setup-steps.svelte';
	import { getCameras } from '$lib/remote/stream.remote';
	import { getDetectors } from '$lib/remote/detector.remote';
	import { setupStep } from '$lib/setup';

	const choices = $derived(await Promise.all([getCameras(), getDetectors()]));
	const cameras = $derived(choices[0]);
	const detectors = $derived(choices[1]);
	const step = $derived(
		setupStep(
			page.url.searchParams.get('step') ?? (page.url.searchParams.has('camera') ? 'finish' : null),
			cameras.length,
			detectors.length
		)
	);
</script>

<svelte:head><title>Setup · AI Detector</title></svelte:head>
<section class="settings-page">
	<SetupSteps current={step} hasCameras={cameras.length > 0} />
	{#if step === 'cameras'}
		<header class="flex flex-wrap items-start justify-between gap-4">
			<div class="flex flex-col gap-2">
				<h1 class="settings-heading">Add your cameras</h1>
				<p class="settings-description">
					Connect your cameras. You’ll choose what to detect in the next step.
				</p>
			</div>
			{#if cameras.length}<Button href={resolve('/streams/add?setup=1')} variant="outline"
					><Plus data-icon="inline-start" />Add camera</Button
				>{/if}
		</header>
		{#if cameras.length}
			<div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
				{#each cameras as camera (camera.id)}
					<CameraPicture id={camera.id} label={camera.label}>
						{#snippet overlay()}
							<div class="flex items-start justify-between gap-3">
								<Badge variant="secondary" class="min-w-0 shrink text-left whitespace-normal"
									>{camera.label}</Badge
								>
								<Button
									href={resolve(`/streams/add?setup=1&id=${camera.id}`)}
									variant="secondary"
									class="pointer-events-auto shrink-0"
									size="sm"
									aria-label={`Edit ${camera.label}`}>Edit</Button
								>
							</div>
						{/snippet}
					</CameraPicture>
				{/each}
			</div>
			<div class="flex flex-col items-start gap-3">
				<Button href={resolve('/setup?step=detectors')}
					>Continue to detectors <ArrowRight data-icon="inline-end" /></Button
				>
				<p class="text-sm text-muted-foreground">
					You can come back to add more cameras at any time.
				</p>
			</div>
		{:else}
			<Empty.Root class="rounded-lg border">
				<Empty.Header
					><Empty.Title>Connect your first camera</Empty.Title><Empty.Description
						>Keep the camera powered on and connected to the same network as this computer. Have its
						username and password ready.</Empty.Description
					></Empty.Header
				>
				<Empty.Content
					><Button href={resolve('/streams/add?setup=1')}
						>Find and add cameras <ArrowRight data-icon="inline-end" /></Button
					></Empty.Content
				>
			</Empty.Root>
		{/if}
	{:else if step === 'detectors'}
		<header class="flex flex-wrap items-start justify-between gap-4">
			<div class="flex flex-col gap-2">
				<h1 class="settings-heading">Choose your detectors</h1>
				<p class="settings-description">
					Choose a preset, then select the cameras it should watch. You can use the same camera in
					several detectors.
				</p>
			</div>
			{#if detectors.length}<Button href={resolve('/detectors/add?setup=1')} variant="outline"
					><Plus data-icon="inline-start" />Add detector</Button
				>{/if}
		</header>
		{#if detectors.length}
			<ul class="divide-y">
				{#each detectors as { detector, meta } (meta.label)}
					<li class="flex items-start justify-between gap-4 py-4 first:pt-0">
						<div class="flex min-w-0 flex-col gap-1">
							<h2 class="font-medium">{meta.label}</h2>
							<p class="text-sm text-muted-foreground">
								{detector.detection.source
									.map(
										(source) =>
											cameras.find((camera) => camera.source === source)?.label ?? 'Custom source'
									)
									.join(', ')}
							</p>
						</div>
						<Button
							href={resolve(`/detectors/add?setup=1&label=${encodeURIComponent(meta.label)}`)}
							variant="outline"
							size="sm"
							aria-label={`Edit ${meta.label}`}>Edit</Button
						>
					</li>
				{/each}
			</ul>
		{:else}
			<Empty.Root class="rounded-lg border">
				<Empty.Header
					><Empty.Title>What should your cameras watch for?</Empty.Title><Empty.Description
						>Add a detector using a preset. Its camera choices include live previews, so you can
						check the view before selecting it.</Empty.Description
					></Empty.Header
				>
				<Empty.Content
					><Button href={resolve('/detectors/add?setup=1')}
						><Plus data-icon="inline-start" />Add detector</Button
					></Empty.Content
				>
			</Empty.Root>
		{/if}
		<div class="flex flex-wrap gap-3">
			<Button
				href={resolve('/setup?step=finish')}
				variant={detectors.length ? 'default' : 'outline'}
				>{detectors.length ? 'Continue to finish setup' : 'Use cameras for viewing only'}
				<ArrowRight data-icon="inline-end" /></Button
			>
		</div>
	{:else}
		<header class="flex flex-col gap-2">
			<h1 class="settings-heading">Finish setup</h1>
			<p class="settings-description">
				Start monitoring, check recordings, and choose whether to connect phone alerts.
			</p>
		</header>
		<div class="flex flex-col gap-6">
			<DetectorRuntime configured={detectors.length > 0} />
			<SetupReview />
		</div>
	{/if}
</section>

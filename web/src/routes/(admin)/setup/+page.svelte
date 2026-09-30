<script lang="ts">
	import { resolve } from '$app/paths';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { Button } from '$lib/components/ui/button';
	import { Badge } from '$lib/components/ui/badge';
	import * as Alert from '$lib/components/ui/alert';
	import { ArrowRight, Plus } from '@lucide/svelte';
	import CameraPicture from '$lib/components/camera-picture.svelte';
	import CameraEditor from '$lib/components/camera-editor.svelte';
	import DetectorEditor from '$lib/components/detector-editor.svelte';
	import SetupReview from '$lib/components/setup-review.svelte';
	import SetupSteps from '$lib/components/setup-steps.svelte';
	import ImportInstallation from '$lib/components/import-installation.svelte';
	import SettingsBackup from '$lib/components/settings-backup.svelte';
	import { Separator } from '$lib/components/ui/separator';
	import { getCameras } from '$lib/remote/stream.remote';
	import { getDetectors } from '$lib/remote/detector.remote';
	import { setupStep } from '$lib/setup';

	const choices = $derived(await Promise.all([getCameras(), getDetectors()]));
	let importing = $state(false);
	let savingDetector = $state(false);
	const cameras = $derived(choices[0]);
	const detectors = $derived(choices[1]);
	const step = $derived(
		setupStep(page.url.searchParams.get('step'), cameras.length, detectors.length)
	);
	const cameraId = $derived(page.url.searchParams.get('camera'));
	const detectorLabel = $derived(page.url.searchParams.get('detector'));
	const adding = $derived(page.url.searchParams.get('add'));
	const camera = $derived(cameras.find((item) => item.id === cameraId));
	const detector = $derived(detectors.find((item) => item.meta.label === detectorLabel));
	const editing = $derived(
		step === 'cameras'
			? cameraId !== null || adding === 'camera'
			: step === 'detectors' && (detectorLabel !== null || adding === 'detector')
	);

	async function showCameras() {
		await goto(resolve('/setup?step=cameras'));
	}
	async function showDetectors() {
		await goto(resolve('/setup?step=detectors'));
	}
	async function imported() {
		importing = false;
		await Promise.all([getCameras().refresh(), getDetectors().refresh()]);
		await goto(resolve('/setup?step=cameras&imported=1'));
	}
</script>

<svelte:head><title>Settings · AI Detector</title></svelte:head>
<section class="settings-page">
	<SetupSteps
		current={step}
		hasCameras={cameras.length > 0}
		disabled={importing || savingDetector}
	/>
	{#if page.url.searchParams.has('imported')}
		<p role="status" class="text-sm text-muted-foreground">
			Your existing setup is ready to review. Previous recordings are available in Recordings.
			Monitoring is stopped until you start it.
		</p>
	{/if}
	{#if step === 'cameras'}
		{#if cameraId && !camera}
			<Alert.Root variant="destructive">
				<Alert.Title>Camera not found</Alert.Title>
				<Alert.Description>This camera may have been removed.</Alert.Description>
			</Alert.Root>
			<div><Button onclick={showCameras} variant="outline">Back to cameras</Button></div>
		{:else if editing}
			{#if !importing}
				{#key cameraId}
					<CameraEditor
						initial={camera}
						onDone={showCameras}
						onCancel={cameras.length ? showCameras : undefined}
					/>
				{/key}
			{/if}
		{:else}
			<header class="flex flex-wrap items-start justify-between gap-4">
				<div class="flex flex-col gap-2">
					<h1 class="settings-heading">Your cameras</h1>
					<p class="settings-description">
						Connect your cameras. You’ll choose what to detect in the next step.
					</p>
				</div>
				<Button href={resolve('/setup?step=cameras&add=camera')} variant="outline"
					><Plus data-icon="inline-start" />Add camera</Button
				>
			</header>
			<div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
				{#each cameras as camera (camera.id)}
					<CameraPicture id={camera.id} label={camera.label} monitored={camera.monitored}>
						{#snippet overlay()}
							<div class="flex items-start justify-between gap-3">
								<Badge variant="secondary" class="min-w-0 shrink text-left whitespace-normal"
									>{camera.label}</Badge
								>
								<Button
									href={resolve(`/setup?step=cameras&camera=${encodeURIComponent(camera.id)}`)}
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
			<div>
				<Button href={resolve('/setup?step=detectors')}
					>Continue to detectors <ArrowRight data-icon="inline-end" /></Button
				>
			</div>
		{/if}
		{#if !cameras.length}
			<ImportInstallation bind:opened={importing} oncomplete={imported} />
		{/if}
	{:else if step === 'detectors'}
		{#if detectorLabel && !detector}
			<Alert.Root variant="destructive">
				<Alert.Title>Detector not found</Alert.Title>
				<Alert.Description>This detector may have been removed.</Alert.Description>
			</Alert.Root>
			<div><Button onclick={showDetectors} variant="outline">Back to detectors</Button></div>
		{:else if editing}
			{#key detectorLabel}
				<DetectorEditor
					bind:pending={savingDetector}
					originalLabel={detectorLabel ?? ''}
					initial={detector?.detector}
					initialPreset={detector?.meta.preset}
					initialConnection={detector?.meta.llmConnection}
					onDone={showDetectors}
					onCancel={detectors.length ? showDetectors : undefined}
				/>
			{/key}
		{:else}
			<header class="flex flex-wrap items-start justify-between gap-4">
				<div class="flex flex-col gap-2">
					<h1 class="settings-heading">Your detectors</h1>
					<p class="settings-description">
						Each detector watches the cameras you select. Cameras can use several detectors.
					</p>
				</div>
				<Button href={resolve('/setup?step=detectors&add=detector')} variant="outline"
					><Plus data-icon="inline-start" />Add detector</Button
				>
			</header>
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
							href={resolve(`/setup?step=detectors&detector=${encodeURIComponent(meta.label)}`)}
							variant="outline"
							size="sm"
							aria-label={`Edit ${meta.label}`}>Edit</Button
						>
					</li>
				{/each}
			</ul>
		{/if}
		{#if !editing || !detectors.length}
			<div>
				<Button
					href={resolve('/setup?step=finish')}
					variant={detectors.length ? 'default' : 'outline'}
					>{detectors.length
						? 'Continue to finish setup'
						: 'Use cameras for viewing only'}<ArrowRight data-icon="inline-end" /></Button
				>
			</div>
		{/if}
	{:else}
		<header class="flex flex-col gap-2">
			<h1 class="settings-heading">Finish setup</h1>
			<p class="settings-description">
				Start monitoring, check recordings, and choose whether to connect phone alerts.
			</p>
		</header>
		<SetupReview configured={detectors.length > 0} />
	{/if}
	{#if !importing && !editing && (cameras.length || detectors.length)}
		<Separator />
		<div><SettingsBackup /></div>
	{/if}
</section>

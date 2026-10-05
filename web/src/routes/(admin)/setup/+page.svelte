<script lang="ts">
	import { resolve } from '$app/paths';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { untrack } from 'svelte';
	import { ArrowRight, Plus } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import CameraAdd from '$lib/components/camera-add.svelte';
	import CameraPicture from '$lib/components/camera-picture.svelte';
	import CategoryDot from '$lib/components/category-dot.svelte';
	import DetectorEditor from '$lib/components/detector-editor.svelte';
	import ImportInstallation from '$lib/components/import-installation.svelte';
	import SetupFinish from '$lib/components/setup-finish.svelte';
	import SetupSteps from '$lib/components/setup-steps.svelte';
	import { plural } from '$lib/format';
	import { getCameras } from '$lib/remote/stream.remote';
	import { getDetectors } from '$lib/remote/detector.remote';
	import { setupStep } from '$lib/setup';

	const choices = $derived(await Promise.all([getCameras(), getDetectors()]));
	const cameras = $derived(choices[0]);
	const detectors = $derived(choices[1]);
	const step = $derived(
		setupStep(page.url.searchParams.get('step'), cameras.length, detectors.length)
	);
	// The first camera and detector open their form directly; later visits show what is saved.
	let addingCamera = $state(untrack(() => cameras.length === 0));
	let addingDetector = $state(untrack(() => detectors.length === 0));
	let editingDetector = $state<string>();
	let importing = $state(false);
	let savingDetector = $state(false);
	const edited = $derived(detectors.find((item) => item.meta.label === editingDetector));

	const headings = {
		cameras: {
			title: 'Connect your cameras',
			description:
				'AI Detector looks for cameras on your network. Keep this computer on the same network as the cameras.'
		},
		detectors: {
			title: 'Choose what to detect',
			description:
				'Pick a preset and the cameras it should watch. You can add more detectors later.'
		},
		finish: {
			title: 'Start monitoring',
			description:
				'Each camera is checked once. Monitoring then keeps running in the background, also when this page is closed.'
		}
	};

	async function show(next: 'detectors' | 'finish') {
		await goto(resolve(`/setup?step=${next}`));
	}
	// Navigate first: the editors finish updating before they are taken off the page.
	async function camerasAdded() {
		await show('detectors');
		addingCamera = false;
	}
	async function detectorSaved() {
		await show('finish');
		addingDetector = false;
		editingDetector = undefined;
	}
	async function imported() {
		importing = false;
		addingCamera = false;
		addingDetector = false;
		await Promise.all([getCameras().refresh(), getDetectors().refresh()]);
		await goto(resolve('/setup?step=cameras&imported=1'));
	}
</script>

<svelte:head><title>Set up · AI Detector</title></svelte:head>

<section class="mx-auto flex w-full max-w-3xl flex-col gap-8">
	<SetupSteps
		current={step}
		hasCameras={cameras.length > 0}
		disabled={importing || savingDetector}
	/>

	{#if !importing}
		<header class="flex flex-col gap-2">
			<h1 class="text-2xl font-semibold tracking-tight text-balance sm:text-3xl">
				{headings[step].title}
			</h1>
			<p class="max-w-prose leading-relaxed text-pretty text-muted-foreground">
				{headings[step].description}
			</p>
		</header>
	{/if}

	{#if page.url.searchParams.has('imported')}
		<p role="status" class="rounded-xl border bg-card px-4 py-3 text-sm">
			Your existing setup is here to review. Previous recordings are in Recordings. Monitoring is
			stopped until you start it in the last step.
		</p>
	{/if}

	{#if step === 'cameras'}
		{#if addingCamera}
			{#if !importing}
				<CameraAdd
					onDone={camerasAdded}
					onCancel={cameras.length ? () => void (addingCamera = false) : undefined}
				/>
			{/if}
			{#if !cameras.length}
				<div class={importing ? '' : 'border-t pt-6'}>
					<ImportInstallation bind:opened={importing} oncomplete={imported} />
				</div>
			{/if}
		{:else}
			<ul class="grid gap-4 sm:grid-cols-2">
				{#each cameras as camera (camera.id)}
					<li>
						<CameraPicture id={camera.id} label={camera.label} monitored={camera.monitored} />
					</li>
				{/each}
			</ul>
			<div class="flex flex-wrap gap-3">
				<Button size="lg" href={resolve('/setup?step=detectors')}>
					Continue<ArrowRight data-icon="inline-end" aria-hidden="true" />
				</Button>
				<Button size="lg" variant="outline" onclick={() => (addingCamera = true)}>
					<Plus data-icon="inline-start" aria-hidden="true" />Add more cameras
				</Button>
			</div>
		{/if}
	{:else if step === 'detectors'}
		{#if addingDetector || edited}
			{#key editingDetector}
				<DetectorEditor
					bind:pending={savingDetector}
					originalLabel={edited?.meta.label ?? ''}
					initial={edited?.detector}
					initialPreset={edited?.meta.preset}
					initialConnection={edited?.meta.llmConnection}
					onDone={detectorSaved}
					onCancel={detectors.length
						? async () => {
								addingDetector = false;
								editingDetector = undefined;
							}
						: undefined}
				/>
			{/key}
			{#if !detectors.length}
				<div class="border-t pt-6">
					<Button variant="ghost" disabled={savingDetector} href={resolve('/setup?step=finish')}>
						Skip — use the cameras for live viewing only
					</Button>
				</div>
			{/if}
		{:else}
			<ul class="panel divide-y">
				{#each detectors as { detector, meta } (meta.label)}
					<li class="flex items-center gap-3 px-4 py-3.5">
						<CategoryDot seed={meta.preset ?? meta.label} />
						<div class="flex min-w-0 flex-1 flex-col">
							<p class="text-sm font-medium">{meta.label}</p>
							<p class="text-sm text-muted-foreground">
								{plural(detector.detection.source.length, ['# camera', '# cameras'])} ·
								{detector.detection.source
									.map(
										(source) =>
											cameras.find((camera) => camera.source === source)?.label ?? 'Custom source'
									)
									.join(', ')}
							</p>
						</div>
						<Button
							variant="outline"
							size="sm"
							aria-label={`Edit ${meta.label}`}
							onclick={() => (editingDetector = meta.label)}>Edit</Button
						>
					</li>
				{/each}
			</ul>
			<div class="flex flex-wrap gap-3">
				<Button size="lg" href={resolve('/setup?step=finish')}>
					Continue<ArrowRight data-icon="inline-end" aria-hidden="true" />
				</Button>
				<Button size="lg" variant="outline" onclick={() => (addingDetector = true)}>
					<Plus data-icon="inline-start" aria-hidden="true" />Add another detector
				</Button>
			</div>
		{/if}
	{:else}
		<SetupFinish configured={detectors.length > 0} />
	{/if}
</section>

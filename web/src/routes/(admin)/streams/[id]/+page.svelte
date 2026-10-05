<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { ChevronRight } from '@lucide/svelte';
	import * as Alert from '$lib/components/ui/alert';
	import { Button } from '$lib/components/ui/button';
	import CameraSettings from '$lib/components/camera-settings.svelte';
	import PageHeader from '$lib/components/page-header.svelte';
	import Pill from '$lib/components/pill.svelte';
	import { getCameras } from '$lib/remote/stream.remote';

	const cameras = $derived(await getCameras());
	const camera = $derived(cameras.find((item) => item.id === page.params.id));
	const back = { href: resolve('/streams'), label: 'Cameras' };
</script>

<svelte:head><title>{camera?.label ?? 'Camera'} · AI Detector</title></svelte:head>
<section class="page">
	{#if !camera}
		<PageHeader {back} title="Camera not found" />
		<Alert.Root variant="destructive" class="max-w-3xl">
			<Alert.Title>Camera not found</Alert.Title>
			<Alert.Description>This camera may have been removed.</Alert.Description>
		</Alert.Root>
	{:else}
		<PageHeader {back} title={camera.label} />
		{#key camera.id}
			<CameraSettings
				initial={camera}
				onDone={async () => void (await goto(resolve('/streams')))}
			/>
		{/key}
		<section class="flex max-w-3xl flex-col gap-3" aria-labelledby="camera-detectors">
			<div class="flex flex-col gap-1">
				<h2 id="camera-detectors" class="text-base font-semibold">Detectors on this camera</h2>
				<p class="text-sm text-muted-foreground">
					{camera.rules.length
						? 'A detector decides what is recorded and who is alerted.'
						: 'This camera is for live viewing only. Add it to a detector to record and alert.'}
				</p>
			</div>
			{#if camera.rules.length}
				<ul class="panel divide-y">
					{#each camera.rules as rule (rule.label)}
						<li>
							<a
								href={resolve(`/detectors/edit?label=${encodeURIComponent(rule.label)}`)}
								class="flex items-center gap-3 px-4 py-3 outline-none hover:bg-accent focus-visible:bg-accent"
							>
								<span class="flex min-w-0 flex-1">
									<Pill tone="category" seed={rule.preset ?? rule.label}>{rule.label}</Pill>
								</span>
								<ChevronRight class="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
							</a>
						</li>
					{/each}
				</ul>
			{/if}
			{#if camera.alerts.length}
				<p class="text-sm text-muted-foreground">Alerts go to {camera.alerts.join(', ')}.</p>
			{/if}
			<div>
				<Button href={resolve('/detectors')} variant="outline" size="sm">
					{camera.rules.length ? 'Manage detectors' : 'Choose a detector'}
				</Button>
			</div>
		</section>
	{/if}
</section>

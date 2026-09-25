<script lang="ts">
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
	import { Badge } from '$lib/components/ui/badge';
	import * as Empty from '$lib/components/ui/empty';
	import * as Alert from '$lib/components/ui/alert';
	import { cameraRuleNames } from '$lib/detector-editor';
	import { getCameras } from '$lib/remote/stream.remote';
	import { getDetectorPresets } from '$lib/remote/detector.remote';
	import { useRuntimeStatus } from '$lib/hooks/runtime-status.svelte';
	import DetectorRuntime from '$lib/components/detector-runtime.svelte';
	import CameraPicture from '$lib/components/camera-picture.svelte';
	import CameraMenu from '$lib/components/camera-menu.svelte';
	const cameras = $derived(await getCameras());
	const { presets, warning: presetWarning } = await getDetectorPresets();
	const monitor = useRuntimeStatus();
	const initial = monitor.query.current ?? (await monitor.query);
	const runtime = $derived(monitor.query.current ?? initial);
	const stale = $derived(monitor.stale);
</script>

<svelte:head><title>Cameras · AI Detector</title></svelte:head>
<section class="flex flex-col gap-6">
	<header class="flex flex-wrap items-start justify-between gap-3">
		<div class="flex flex-col gap-1">
			<h1 class="text-2xl font-semibold tracking-tight">Cameras</h1>
			<p class="text-sm text-muted-foreground">Live views from your cameras.</p>
		</div>
		{#if cameras.length}<Button href={resolve('/streams/add')}>Add camera</Button>{/if}
	</header>
	{#if presetWarning}
		<Alert.Root variant="destructive">
			<Alert.Title>Monitoring preset names are unavailable</Alert.Title>
			<Alert.Description>
				{presetWarning} Cameras below show their saved detector names. Their settings are unchanged.
			</Alert.Description>
		</Alert.Root>
	{/if}
	<DetectorRuntime configured={cameras.some((camera) => camera.monitored)} compact />
	<div class="grid gap-4 lg:grid-cols-2">
		{#each cameras as camera (camera.id)}
			{@const status = runtime.cameras.find((item) => item.id === camera.id)}
			<div class="flex min-w-0 flex-col gap-3">
				<CameraPicture id={camera.id} label={camera.label}>
					{#snippet overlay()}
						<div class="flex items-start justify-between gap-3">
							<div class="flex min-w-0 flex-wrap items-center gap-2">
								<Badge variant="secondary" class="max-w-full text-left whitespace-normal"
									>{camera.label}</Badge
								>
								<Badge
									variant={stale || status?.error || status?.recordingError
										? 'destructive'
										: 'secondary'}
									>{!camera.monitored
										? 'View only'
										: stale || !runtime.managed
											? 'Status unavailable'
											: status?.error || status?.recordingError
												? 'Needs attention'
												: status?.state === 'monitoring'
													? 'Monitoring'
													: status?.state === 'paused' || runtime.readiness === 'idle'
														? 'Paused'
														: status?.state === 'offline' || status?.state === 'failed'
															? 'Needs attention'
															: runtime.managed
																? 'Preparing'
																: 'Status unavailable'}</Badge
								>
								{#if camera.monitored}
									<Badge variant="secondary" class="max-w-full text-left whitespace-normal"
										>{cameraRuleNames(camera.rules, presets)}</Badge
									>
								{/if}
							</div>
							<div class="pointer-events-auto shrink-0">
								<CameraMenu
									id={camera.id}
									label={camera.label}
									monitored={camera.monitored}
									setupComplete={camera.setupComplete}
								/>
							</div>
						</div>
					{/snippet}
				</CameraPicture>
				{#if status?.error}<p role="alert" class="text-sm text-destructive">
						{status.error}
					</p>{/if}
				{#if status?.recordingError}<p role="alert" class="text-sm text-destructive">
						{status.recordingError}
					</p>{/if}
			</div>
		{:else}<Empty.Root
				><Empty.Header
					><Empty.Title>No cameras yet</Empty.Title><Empty.Description
						>Add a camera to check its picture and start monitoring.</Empty.Description
					></Empty.Header
				><Empty.Content
					><Button href={resolve('/streams/add')}>Add your first camera</Button></Empty.Content
				></Empty.Root
			>{/each}
	</div>
</section>

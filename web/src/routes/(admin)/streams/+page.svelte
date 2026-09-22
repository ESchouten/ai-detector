<script lang="ts">
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
	import { Badge } from '$lib/components/ui/badge';
	import * as Card from '$lib/components/ui/card';
	import * as Empty from '$lib/components/ui/empty';
	import * as Alert from '$lib/components/ui/alert';
	import { cameraRuleNames } from '$lib/detector-editor';
	import { getCameras } from '$lib/remote/stream.remote';
	import { getDetectorPresets } from '$lib/remote/detector.remote';
	import { getRuntime } from '$lib/remote/runtime.remote';
	import DetectorRuntime from '$lib/components/detector-runtime.svelte';
	import CameraPicture from '$lib/components/camera-picture.svelte';
	const cameras = $derived(await getCameras());
	const { catalogue, warning: catalogueWarning } = await getDetectorPresets();
	let runtime = $state(await getRuntime());
	let connectionLost = $state(false);
	let lastCheckedAt = $state(Date.now());
	let now = $state(Date.now());
	const stale = $derived(connectionLost || now - lastCheckedAt > 10000);
	onMount(() => {
		let active = true;
		const clock = setInterval(() => (now = Date.now()), 1000);
		let timer: ReturnType<typeof setTimeout>;
		async function refresh() {
			try {
				await getRuntime().refresh();
				runtime = await getRuntime();
				connectionLost = false;
				lastCheckedAt = Date.now();
			} catch {
				connectionLost = true;
			}
			if (active) timer = setTimeout(refresh, 3000);
		}
		timer = setTimeout(refresh, 3000);
		return () => {
			active = false;
			clearTimeout(timer);
			clearInterval(clock);
		};
	});
</script>

<svelte:head><title>Cameras · AI Detector</title></svelte:head>
<section class="flex flex-col gap-6">
	<header class="flex flex-wrap items-start justify-between gap-3">
		<div class="flex flex-col gap-1">
			<h1 class="text-2xl font-semibold tracking-tight">Cameras</h1>
			<p class="text-sm text-muted-foreground">
				See what each camera watches for and where its alerts go.
			</p>
		</div>
		<Button href={resolve('/streams/add')}>Add camera</Button>
	</header>
	{#if catalogueWarning}
		<Alert.Root variant="destructive">
			<Alert.Title>Monitoring preset names are unavailable</Alert.Title>
			<Alert.Description>
				{catalogueWarning} Cameras below show their saved rule names. Their settings are unchanged.
			</Alert.Description>
		</Alert.Root>
	{/if}
	<DetectorRuntime configured={cameras.some((camera) => camera.monitored)} compact />
	{#if stale}<p role="alert" class="text-sm text-destructive">
			No recent status from the app. Last checked {new Date(lastCheckedAt).toLocaleTimeString()}.
			Reopen AI Detector if it does not reconnect.
		</p>{/if}
	<div class="grid gap-4 lg:grid-cols-2">
		{#each cameras as camera (camera.id)}
			{@const status = runtime.cameras.find((item) => item.id === camera.id)}
			<Card.Root
				><Card.Header
					><Card.Title class="flex items-center justify-between gap-3"
						>{camera.label}<Badge
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
						></Card.Title
					><Card.Description
						>{camera.monitored
							? cameraRuleNames(camera.rules, catalogue.presets)
							: 'Live viewing only. No events or alerts.'}</Card.Description
					></Card.Header
				>
				<Card.Content class="flex flex-col gap-3"
					><CameraPicture id={camera.id} label={camera.label} />
					<p class="text-sm text-muted-foreground">
						Alerts: {camera.alerts.length ? camera.alerts.join(', ') : 'Not connected'}
					</p>
					{#if status?.lastFrameAt}<p class="text-sm text-muted-foreground">
							Last picture received: {new Date(status.lastFrameAt).toLocaleTimeString()}
						</p>{/if}{#if status?.error}<p role="alert" class="text-sm text-destructive">
							{status.error}
						</p>{/if}
					{#if status?.recordingError}<p role="alert" class="text-sm text-destructive">
							{status.recordingError}
						</p>{/if}</Card.Content
				>
				<Card.Footer class="flex flex-wrap gap-2"
					>{#if !camera.setupComplete}<Button href={resolve(`/setup?camera=${camera.id}`)}
							>Finish setup</Button
						>{/if}
					<Button href={resolve(`/streams/add?id=${camera.id}`)} variant="outline"
						>Camera settings</Button
					>{#if camera.monitored}<Button
							href={resolve(`/notifications/add?camera=${camera.id}`)}
							variant="outline">Connect alerts</Button
						>{/if}</Card.Footer
				>
			</Card.Root>
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

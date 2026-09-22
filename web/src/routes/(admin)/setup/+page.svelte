<script lang="ts">
	import { untrack } from 'svelte';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { Button } from '$lib/components/ui/button';
	import * as NativeSelect from '$lib/components/ui/native-select';
	import CameraEditor from '$lib/components/camera-editor.svelte';
	import CameraSetupProgress from '$lib/components/camera-setup-progress.svelte';
	import DetectorRuntime from '$lib/components/detector-runtime.svelte';
	import { getCameras } from '$lib/remote/stream.remote';
	const cameras = $derived(await getCameras());
	const addingFirstCamera = untrack(() => cameras.length === 0);
	const incomplete = $derived(cameras.filter((camera) => !camera.setupComplete));
	const selected = $derived(
		cameras.find((camera) => camera.id === page.url.searchParams.get('camera')) ??
			incomplete[0] ??
			cameras[0]
	);
</script>

<svelte:head><title>{cameras.length ? 'Settings' : 'Setup'} · AI Detector</title></svelte:head>
{#if addingFirstCamera || cameras.length === 0}<CameraEditor />{:else}
	<section class="flex w-full max-w-3xl flex-col gap-6">
		<header class="flex flex-col gap-2">
			<h1 class="text-2xl font-semibold tracking-tight">
				{incomplete.length ? 'Finish setup' : 'Settings'}
			</h1>
			<p class="text-muted-foreground">
				Manage monitoring on this computer. Camera and alert settings are available from their own
				pages.
			</p>
		</header>
		<DetectorRuntime configured={cameras.some((camera) => camera.monitored)} />
		{#if cameras.length > 1}<label for="setup-camera" class="text-sm font-medium"
				>Camera to set up</label
			>
			<NativeSelect.Root
				id="setup-camera"
				value={selected.id}
				onchange={(event) => goto(resolve(`/setup?camera=${event.currentTarget.value}`))}
			>
				{#each cameras as camera (camera.id)}<NativeSelect.Option value={camera.id}
						>{camera.label}{camera.setupComplete
							? ' · Setup finished'
							: ' · Continue setup'}</NativeSelect.Option
					>{/each}
			</NativeSelect.Root>{/if}
		{#key selected.id}<CameraSetupProgress id={selected.id} />{/key}
		<div class="flex flex-wrap gap-3">
			<Button href={resolve('/streams/add')}>Add camera</Button><Button
				href={resolve('/notifications')}
				variant="outline">Manage alerts</Button
			>
		</div>
		<details>
			<summary class="cursor-pointer text-sm">Advanced settings</summary>
			<p class="my-3 text-sm text-muted-foreground">
				Manage custom models, shared monitoring rules and JSON configuration.
			</p>
			<Button href={resolve('/detectors')} variant="outline">Advanced monitoring rules</Button>
		</details>
	</section>
{/if}

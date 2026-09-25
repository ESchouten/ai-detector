<script lang="ts">
	import { page } from '$app/state';
	import CameraEditor from '$lib/components/camera-editor.svelte';
	import * as Alert from '$lib/components/ui/alert';
	import { getCamera, getCameras } from '$lib/remote/stream.remote';
	const setupMode = $derived(page.url.searchParams.get('setup') === '1');
	const id = $derived(page.url.searchParams.get('id') ?? '');
	const cameras = $derived(await getCameras());
	const camera = $derived(id ? await getCamera(id) : undefined);
</script>

<svelte:head><title>Camera settings · AI Detector</title></svelte:head>
{#if id && !camera}<Alert.Root variant="destructive"
		><Alert.Title>Camera not found</Alert.Title><Alert.Description
			>Return to Cameras and choose a saved camera.</Alert.Description
		></Alert.Root
	>{:else}{#key id}<CameraEditor
			initial={camera}
			{setupMode}
			hasCameras={cameras.length > 0}
		/>{/key}{/if}

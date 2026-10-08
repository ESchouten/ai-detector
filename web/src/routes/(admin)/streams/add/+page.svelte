<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import CameraAdd from '$lib/components/camera-add.svelte';
	import PageHeader from '$lib/components/page-header.svelte';

	const cameras = () => goto(resolve('/streams'));
</script>

<svelte:head><title>Add camera · AI Detector</title></svelte:head>
<section class="page-narrow">
	<PageHeader
		back={{ href: resolve('/streams'), label: 'Cameras' }}
		title="Add cameras"
		description="Choose the cameras to connect, or enter a stream URL. Keep them on the same network as this computer."
	/>
	<CameraAdd onDone={cameras} onCancel={cameras} />
</section>

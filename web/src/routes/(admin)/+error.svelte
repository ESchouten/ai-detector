<script lang="ts">
	import { page } from '$app/state';
</script>

<svelte:head><title>Needs attention · AI Detector</title></svelte:head>

<h1>Something went wrong!</h1>
<p>{page.error?.message}</p>

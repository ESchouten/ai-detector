<script lang="ts">
	import './layout.css';
	import favicon from '$lib/assets/favicon.svg';
	import { Toaster } from '$lib/components/ui/sonner';

	let { children } = $props();
</script>

<svelte:head>
	<title>AI Detector</title>
	<link rel="icon" href={favicon} />
</svelte:head>

{@render children()}
<Toaster />

<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
</script>

<svelte:head><title>Needs attention · AI Detector</title></svelte:head>

<section class="settings-page">
	<h1 class="settings-heading">This page needs attention</h1>
	<p>{page.error?.message}</p>
	<div class="flex flex-wrap gap-3">
		<Button href={resolve('/recovery')} variant="outline">Recover settings</Button><Button
			href={resolve('/logs/diagnostics')}
			variant="outline"
			download>Download diagnostics</Button
		>
	</div>
</section>

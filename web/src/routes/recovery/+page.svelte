<script lang="ts">
	import { enhance } from '$app/forms';
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
	import * as Alert from '$lib/components/ui/alert';
	let { data, form } = $props();
</script>

<svelte:head><title>Recover settings · AI Detector</title></svelte:head>
<main class="mx-auto flex min-h-dvh max-w-lg flex-col justify-center gap-6 p-6">
	<h1 class="text-2xl font-semibold">Recover settings</h1>
	<p class="text-muted-foreground">
		Restore the last settings AI Detector could read. The current files are kept as copies for
		troubleshooting. Recordings are kept.
	</p>
	{#if form?.message}<Alert.Root variant="destructive"
			><Alert.Title>Recovery did not finish</Alert.Title><Alert.Description
				>{form.message}</Alert.Description
			></Alert.Root
		>{/if}
	{#if data.available}<form method="POST" use:enhance>
			<Button type="submit">Restore saved settings</Button>
		</form>{:else}<p>
			No valid recovery snapshot is available. Restore config.json and app.json from your settings
			backup, or ask for help using the diagnostics download.
		</p>{/if}
	<div class="flex flex-wrap gap-3">
		<Button href={resolve('/logs/diagnostics')} variant="outline" download
			>Download diagnostics</Button
		><Button href={resolve('/setup')} variant="outline">Back to settings</Button>
	</div>
</main>

<script lang="ts">
	import { enhance } from '$app/forms';
	import { resolve } from '$app/paths';
	import { Download } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import * as Alert from '$lib/components/ui/alert';
	import BrandMark from '$lib/components/brand-mark.svelte';
	let { data, form } = $props();
</script>

<svelte:head><title>Recover settings · AI Detector</title></svelte:head>
<main class="mx-auto flex min-h-dvh max-w-lg flex-col justify-center gap-6 p-6">
	<BrandMark class="size-11 rounded-xl [&>svg]:size-6" />
	<div class="flex flex-col gap-2">
		<h1 class="text-2xl font-semibold tracking-tight">Recover settings</h1>
		<p class="leading-relaxed text-muted-foreground">
			Restore the last settings AI Detector could read. The current files are kept as copies for
			troubleshooting. Recordings are kept.
		</p>
	</div>
	{#if form?.message}
		<Alert.Root variant="destructive">
			<Alert.Title>Recovery did not finish</Alert.Title>
			<Alert.Description>{form.message}</Alert.Description>
		</Alert.Root>
	{/if}
	{#if data.available}
		<form method="POST" use:enhance>
			<Button type="submit" size="lg">Restore saved settings</Button>
		</form>
	{:else}
		<p class="rounded-xl border bg-card px-4 py-3 text-sm leading-relaxed">
			No valid recovery snapshot is available. Restore config.json and app.json from your settings
			backup, or ask for help using the diagnostics download.
		</p>
	{/if}
	<div class="flex flex-wrap gap-3">
		<Button href={resolve('/logs/diagnostics')} variant="outline" download>
			<Download data-icon="inline-start" aria-hidden="true" />Download diagnostics
		</Button>
		<Button href={resolve('/')} variant="ghost">Back to the app</Button>
	</div>
</main>

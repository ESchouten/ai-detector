<script lang="ts">
	import { enhance } from '$app/forms';
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Separator } from '$lib/components/ui/separator';
	import * as Field from '$lib/components/ui/field';
	import * as Alert from '$lib/components/ui/alert';
	let { data, form } = $props();
	const gb = (bytes: number) => (bytes / 1024 ** 3).toFixed(1);
</script>

<svelte:head><title>Storage · AI Detector</title></svelte:head>
<section class="settings-page">
	<header class="flex flex-col gap-2">
		<h1 class="settings-heading">Storage</h1>
		<p class="settings-description">
			{gb(data.space.available)} GB free of {gb(data.space.total)} GB. Recordings are kept until you remove
			them.
		</p>
	</header>
	{#if data.space.low}<Alert.Root variant="destructive"
			><Alert.Title>Storage is almost full</Alert.Title><Alert.Description
				>Free some space so new recordings can be saved.</Alert.Description
			></Alert.Root
		>{/if}
	{#if form?.message}<p role="status" class="text-sm">{form.message}</p>{/if}
	<div class="flex flex-col gap-4">
		<h2 class="text-lg font-medium">Remove old recordings</h2>
		<p class="text-sm text-muted-foreground">
			Download any recordings you want to keep before removing them.
		</p>
		<Button href={resolve('/detections')} variant="outline" class="self-start"
			>Open recordings</Button
		>
		<form method="POST" action="?/preview" use:enhance class="flex flex-col items-start gap-4">
			<Field.Group
				><Field.Field
					><Field.Label for="before-date">Recordings before</Field.Label><Input
						id="before-date"
						name="before"
						type="date"
						max={new Date().toISOString().slice(0, 10)}
						required
					/></Field.Field
				></Field.Group
			>
			<Button type="submit" variant="outline">Review cleanup</Button>
		</form>
		{#if form?.revision}
			<Alert.Root
				><Alert.Title>{form.count} recordings before {form.before}</Alert.Title><Alert.Description
					>Removing these recordings cannot be undone. Camera settings and more recent recordings
					are kept.</Alert.Description
				></Alert.Root
			>
			{#if form.count}<form method="POST" action="?/remove" use:enhance>
					<input type="hidden" name="before" value={form.before} /><input
						type="hidden"
						name="revision"
						value={form.revision}
					/><Button type="submit" variant="destructive">Remove {form.count} recordings</Button>
				</form>{/if}
		{/if}
	</div>
	<Separator />
	<details>
		<summary class="cursor-pointer text-sm font-medium">Model cache</summary>
		<div class="mt-4 flex flex-col items-start gap-4">
			<p class="text-sm text-muted-foreground">
				Pause monitoring before clearing prepared models and unused downloads. The next start will
				prepare models again; NVIDIA optimization can take several minutes.
			</p>
			<form method="POST" action="?/cache" use:enhance>
				<Button type="submit" variant="outline" disabled={!data.managed}>Clear model cache</Button>
			</form>
		</div>
	</details>
</section>

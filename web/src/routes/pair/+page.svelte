<script lang="ts">
	import { onMount } from 'svelte';
	import { enhance } from '$app/forms';
	import { invalidateAll } from '$app/navigation';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import * as Field from '$lib/components/ui/field';
	import * as Alert from '$lib/components/ui/alert';
	let { form } = $props();
	let code = $state('');
	let scanned = $state(false);
	let pending = $state(false);
	onMount(() => {
		code = new URLSearchParams(location.hash.slice(1)).get('code') ?? '';
		scanned = /^[0-9]{6}$/.test(code);
		if (location.hash) history.replaceState(null, '', location.pathname);
		// Earlier pairing cookies use SameSite=Strict and may be absent on an
		// external link's first request. Recheck from this page before asking to pair.
		void invalidateAll();
	});
</script>

<svelte:head><title>Connect device · AI Detector</title></svelte:head>
<main class="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-6 p-6">
	<div class="flex flex-col gap-2">
		<h1 class="text-2xl font-semibold">Connect to AI Detector</h1>
		<p class="text-muted-foreground">
			{#if scanned}
				Your code is filled in. Tap Connect device to open the dashboard on this device.
			{:else}
				On the computer running AI Detector, open Connected devices and choose Connect another
				device.
			{/if}
		</p>
	</div>
	<form
		class="flex flex-col gap-6"
		method="POST"
		use:enhance={() => {
			pending = true;
			return async ({ update }) => {
				await update();
				pending = false;
			};
		}}
	>
		<Field.Group>
			<Field.Field
				><Field.Label for="pair-code">Six-digit code</Field.Label><Input
					id="pair-code"
					name="code"
					bind:value={code}
					inputmode="numeric"
					pattern={'[0-9]{6}'}
					maxlength={6}
					autocomplete="one-time-code"
					required
				/></Field.Field
			>
			<Field.Field
				><Field.Label for="device-name">Device name (optional)</Field.Label><Input
					id="device-name"
					name="name"
					placeholder="e.g. My phone"
					maxlength={80}
				/></Field.Field
			>
		</Field.Group>
		{#if form?.message}<Alert.Root variant="destructive"
				><Alert.Title>Could not connect</Alert.Title><Alert.Description
					>{form.message}</Alert.Description
				></Alert.Root
			>{/if}
		<Button type="submit" disabled={pending}>{pending ? 'Connecting…' : 'Connect device'}</Button>
	</form>
</main>

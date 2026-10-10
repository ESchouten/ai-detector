<script lang="ts">
	import { onMount } from 'svelte';
	import { enhance } from '$app/forms';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import * as Field from '$lib/components/ui/field';
	import * as Alert from '$lib/components/ui/alert';
	import BrandMark from '$lib/components/brand-mark.svelte';
	let { form } = $props();
	let code = $state('');
	let scanned = $state(false);
	let pending = $state(false);
	onMount(() => {
		code = new URLSearchParams(location.hash.slice(1)).get('code') ?? '';
		scanned = /^[0-9]{6}$/.test(code);
		if (location.hash) history.replaceState(null, '', location.pathname);
	});
</script>

<svelte:head><title>Connect device · AI Detector</title></svelte:head>
<main class="mx-auto flex min-h-dvh max-w-sm flex-col justify-center gap-8 p-6">
	<div class="flex flex-col gap-4">
		<BrandMark class="size-11 rounded-xl [&>svg]:size-6" />
		<div class="flex flex-col gap-2">
			<h1 class="text-2xl font-semibold tracking-tight">Connect to AI Detector</h1>
			<p class="leading-relaxed text-muted-foreground">
				{#if scanned}
					Your code is filled in. Tap Connect device to open the dashboard here.
				{:else}
					On the computer running AI Detector, open Settings → Devices and choose Connect a device.
					Enter the code it shows.
				{/if}
			</p>
		</div>
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
			<Field.Field>
				<Field.Label for="pair-code">Six-digit code</Field.Label>
				<Input
					id="pair-code"
					name="code"
					bind:value={code}
					inputmode="numeric"
					pattern={'[0-9]{6}'}
					maxlength={6}
					autocomplete="one-time-code"
					class="h-12 text-center font-mono text-xl tracking-[0.3em] md:text-xl"
					required
				/>
			</Field.Field>
			<Field.Field>
				<Field.Label for="device-name">
					Name for this device <span class="font-normal text-muted-foreground">(optional)</span>
				</Field.Label>
				<Input id="device-name" name="name" placeholder="e.g. My phone" maxlength={80} />
			</Field.Field>
		</Field.Group>
		{#if form?.message}
			<Alert.Root variant="destructive">
				<Alert.Title>Could not connect</Alert.Title>
				<Alert.Description>{form.message}</Alert.Description>
			</Alert.Root>
		{/if}
		<Button type="submit" size="lg" disabled={pending}>
			{pending ? 'Connecting…' : 'Connect device'}
		</Button>
	</form>
</main>

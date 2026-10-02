<script lang="ts">
	import { enhance } from '$app/forms';
	import { Button } from '$lib/components/ui/button';
	import { Separator } from '$lib/components/ui/separator';
	import * as Alert from '$lib/components/ui/alert';
	import * as Field from '$lib/components/ui/field';
	import * as NativeSelect from '$lib/components/ui/native-select';
	let { data, form } = $props();
	let creating = $state(false);
</script>

<svelte:head><title>Connected devices · AI Detector</title></svelte:head>
<section class="settings-page">
	<header class="flex flex-col gap-2">
		<h1 class="settings-heading">Connected devices</h1>
		<p class="settings-description">
			Connect a phone or another computer on the same network. Your browser remembers its access.
		</p>
	</header>
	<form
		class="flex flex-col items-start gap-4"
		method="POST"
		action="?/connect"
		use:enhance={() => {
			creating = true;
			return async ({ update }) => {
				await update();
				creating = false;
			};
		}}
	>
		{#if data.networks.length > 1}
			<Field.Field>
				<Field.Label for="pairing-network">Network</Field.Label>
				<NativeSelect.Root id="pairing-network" name="address" value={data.networks[0].address}>
					{#each data.networks as network (network.address)}
						<NativeSelect.Option value={network.address}
							>{network.name} · {network.address}</NativeSelect.Option
						>
					{/each}
				</NativeSelect.Root>
				<Field.Description>Choose the network your phone is connected to.</Field.Description>
			</Field.Field>
		{/if}
		<Button type="submit" disabled={creating}
			>{creating
				? 'Creating code…'
				: form?.qr
					? 'Create a new code'
					: 'Connect another device'}</Button
		>
	</form>
	{#if form?.qr}
		<div class="flex flex-col items-start gap-3">
			<img src={form.qr} alt="Scan to connect to AI Detector" class="size-64 rounded-md" />
			<p>Scan this QR code with your phone’s camera, then tap Connect.</p>
			<p class="text-sm text-muted-foreground">
				Or enter <strong class="font-mono text-xl tracking-widest">{form.code}</strong> on the pairing
				page.
			</p>
			<p class="text-sm text-muted-foreground">
				Valid until {new Date(form.expires!).toLocaleTimeString()}. Keep this code private.
			</p>
			<Button href={form.link} variant="outline">Open pairing page</Button>
		</div>
	{/if}
	{#if form?.message}<Alert.Root variant="destructive"
			><Alert.Title>Could not connect device</Alert.Title><Alert.Description
				>{form.message}</Alert.Description
			></Alert.Root
		>{/if}
	{#if !data.devices.length}<p class="text-sm text-muted-foreground">
			No other devices are connected yet.
		</p>{/if}
	<div class="flex flex-col gap-4">
		{#each data.devices as device, index (device.id)}
			{#if index}<Separator />{/if}
			<div class="flex items-center justify-between gap-4">
				<div>
					<p class="font-medium">
						{device.name}{device.id === data.current ? ' (this browser)' : ''}
					</p>
					<p class="text-sm text-muted-foreground">
						Connected {new Date(device.created).toLocaleDateString()}
					</p>
				</div>
				{#if device.id !== data.current}<form method="POST" action="?/remove" use:enhance>
						<input type="hidden" name="id" value={device.id} /><Button
							variant="outline"
							type="submit">Remove access</Button
						>
					</form>{/if}
			</div>
		{/each}
	</div>
	{#if !data.encrypted}<p class="text-sm text-muted-foreground">
			This dashboard uses HTTP. Use it on a trusted local network. Pairing limits access; HTTPS or a
			secure tunnel is needed to encrypt network traffic.
		</p>{/if}
</section>

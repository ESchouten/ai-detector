<script lang="ts">
	import { enhance } from '$app/forms';
	import { resolve } from '$app/paths';
	import { Laptop, QrCode } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import * as Alert from '$lib/components/ui/alert';
	import * as Field from '$lib/components/ui/field';
	import * as NativeSelect from '$lib/components/ui/native-select';
	import PageHeader from '$lib/components/page-header.svelte';
	import Pill from '$lib/components/pill.svelte';
	import { calendarDate, clockTime } from '$lib/format';
	let { data, form } = $props();
	let creating = $state(false);
</script>

<section class="page-narrow">
	<PageHeader
		back={{ href: resolve('/settings'), label: 'Settings' }}
		title="Devices"
		description="Open this dashboard on a phone or another computer on the same network. Each browser is remembered until you remove it."
	/>

	<div class="panel flex flex-col gap-5 p-5">
		{#if form?.qr}
			<div class="flex flex-col gap-5 sm:flex-row sm:items-center">
				<img
					src={form.qr}
					alt="Scan to connect to AI Detector"
					class="size-52 shrink-0 rounded-xl border bg-white p-2"
				/>
				<div class="flex min-w-0 flex-col items-start gap-3">
					<p class="text-sm leading-relaxed">
						Scan this code with your phone’s camera, then tap <strong>Connect device</strong>.
					</p>
					<p class="text-sm text-muted-foreground">Or open the pairing page and enter</p>
					<p class="font-mono text-3xl font-semibold tracking-[0.25em] tabular-nums">{form.code}</p>
					<p class="text-sm text-muted-foreground">
						Valid until {clockTime(form.expires!)}. Keep this code private.
					</p>
					<Button href={form.link} variant="outline" size="sm">Open pairing page</Button>
				</div>
			</div>
		{/if}
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
				<Field.Field class="max-w-md">
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
			<Button type="submit" variant={form?.qr ? 'outline' : 'default'} disabled={creating}>
				<QrCode data-icon="inline-start" aria-hidden="true" />
				{creating ? 'Creating code…' : form?.qr ? 'Create a new code' : 'Connect a device'}
			</Button>
		</form>
		{#if form?.message}
			<Alert.Root variant="destructive">
				<Alert.Title>Could not connect device</Alert.Title>
				<Alert.Description>{form.message}</Alert.Description>
			</Alert.Root>
		{/if}
	</div>

	<section class="flex flex-col gap-3" aria-labelledby="devices-connected">
		<h2 id="devices-connected" class="text-base font-semibold">Connected devices</h2>
		{#if data.devices.length}
			<ul class="panel divide-y">
				{#each data.devices as device (device.id)}
					<li class="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3.5">
						<span
							class="flex size-9 shrink-0 items-center justify-center rounded-lg bg-secondary text-secondary-foreground"
						>
							<Laptop class="size-[1.125rem]" aria-hidden="true" />
						</span>
						<div class="flex min-w-0 flex-1 flex-col">
							<p class="flex flex-wrap items-center gap-2 text-sm font-medium">
								{device.name}
								{#if device.id === data.current}<Pill>This browser</Pill>{/if}
							</p>
							<p class="text-sm text-muted-foreground">
								Connected {calendarDate(device.created)}
							</p>
						</div>
						{#if device.id !== data.current}
							<form method="POST" action="?/remove" use:enhance>
								<input type="hidden" name="id" value={device.id} />
								<Button variant="outline" size="sm" type="submit">Remove access</Button>
							</form>
						{/if}
					</li>
				{/each}
			</ul>
		{:else}
			<p class="text-sm text-muted-foreground">
				No other devices yet. The computer running AI Detector always has access.
			</p>
		{/if}
	</section>
	{#if !data.encrypted}
		<p class="text-sm leading-relaxed text-muted-foreground">
			This dashboard uses HTTP, so use it on a network you trust. Pairing limits who can open it;
			HTTPS or a secure tunnel is needed to encrypt the traffic.
		</p>
	{/if}
</section>

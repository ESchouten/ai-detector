<script lang="ts">
	import { untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import * as Field from '$lib/components/ui/field';
	import * as Alert from '$lib/components/ui/alert';
	import * as Card from '$lib/components/ui/card';
	import { deleteTelegram, saveAlerts, getTelegrams } from '$lib/remote/exporter.remote';
	import { getCameras } from '$lib/remote/stream.remote';
	import { recipientCameraIds } from '$lib/alert-recipients';
	import { errorMessage } from '$lib/remote-errors';
	import type { TelegramMeta } from '$lib/schema';
	import TelegramConnection from './telegram-connection.svelte';

	let {
		originalLabel,
		initial,
		cameraId = ''
	}: { originalLabel: string; initial?: TelegramMeta; cameraId?: string } = $props();
	const cameras = await getCameras();
	let label = $state(untrack(() => initial?.label ?? 'Farm alerts'));
	let token = $state(untrack(() => initial?.token ?? ''));
	let chat = $state(untrack(() => initial?.chat ?? ''));
	let cameraIds = $state(untrack(() => recipientCameraIds(cameras, originalLabel, cameraId)));
	let pending = $state(false);
	let connecting = $state(false);
	let received = $state(false);
	let error = $state('');
	let confirmRemove = $state(false);
	let saved = $state<{ label: string; cameras: string[] }>();
	const connectionUnchanged = $derived(initial && token === initial.token && chat === initial.chat);
	const canSave = $derived(
		label.trim() && cameraIds.length && token && chat && (connectionUnchanged || received)
	);
	const back = $derived(
		cameraId ? resolve(`/setup?camera=${cameraId}`) : resolve('/notifications')
	);
	async function save(event: SubmitEvent) {
		event.preventDefault();
		if (!canSave) return;
		pending = true;
		error = '';
		const summary = {
			label,
			cameras: cameras
				.filter((camera) => cameraIds.includes(camera.id))
				.map((camera) => camera.label)
		};
		try {
			await saveAlerts({
				original: originalLabel || undefined,
				label,
				token,
				chat,
				cameraIds,
				received
			}).updates(getCameras(), getTelegrams());
			saved = summary;
		} catch (cause) {
			error = errorMessage(cause, 'Could not save alerts. Your choices are still here.');
		} finally {
			pending = false;
		}
	}
	async function remove() {
		pending = true;
		error = '';
		try {
			await deleteTelegram({ label: originalLabel }).updates(getCameras(), getTelegrams());
			await goto(resolve('/notifications'));
		} catch (cause) {
			error = errorMessage(cause, 'Could not remove this recipient.');
		} finally {
			pending = false;
		}
	}
</script>

<section class="flex w-full max-w-2xl flex-col gap-6">
	<header class="flex flex-col gap-2">
		<h1 class="text-2xl font-semibold tracking-tight">
			{saved ? 'Alerts are connected' : initial ? 'Manage alerts' : 'Connect alerts'}
		</h1>
		<p class="text-muted-foreground">
			{saved
				? cameraId
					? 'Return to setup to check the remaining steps for your camera.'
					: 'Your choices are saved. Open alerts to manage your recipients.'
				: initial
					? 'Keep using your saved recipient and choose which cameras send alerts.'
					: 'Connect your phone, confirm a test message, then choose your cameras.'}
		</p>
	</header>
	{#if saved}
		<Alert.Root
			><Alert.Title>{saved.label}</Alert.Title><Alert.Description
				>Alerts are connected to {saved.cameras.join(', ')}.</Alert.Description
			></Alert.Root
		>
		<div class="flex flex-wrap gap-3">
			{#if cameraId}<Button href={back}>Back to setup</Button>{/if}
			<Button href={resolve('/notifications')} variant={cameraId ? 'outline' : 'default'}
				>Open alerts</Button
			>
			<Button href={resolve('/detections')} variant="outline">Open recordings</Button>
		</div>
	{:else}
		<form class="flex flex-col gap-6" onsubmit={save}>
			<Card.Root>
				<Card.Header
					><Card.Title>1. Your Telegram recipient</Card.Title><Card.Description
						>Alerts are optional. Local monitoring works without Telegram.</Card.Description
					></Card.Header
				>
				<Card.Content class="flex flex-col gap-5">
					<Field.Field
						><Field.Label for="notification-label">Recipient name</Field.Label><Input
							id="notification-label"
							bind:value={label}
							disabled={pending}
							required
							placeholder="e.g. Farmer’s phone"
						/></Field.Field
					>
					<TelegramConnection
						{initial}
						bind:token
						bind:chat
						bind:received
						bind:busy={connecting}
						disabled={pending}
					/>
				</Card.Content>
			</Card.Root>
			<Card.Root>
				<Card.Header
					><Card.Title>2. Choose your cameras</Card.Title><Card.Description
						>{initial
							? 'Existing camera assignments are already selected. Add another camera below.'
							: 'Choose which cameras will send alerts to this recipient.'}</Card.Description
					></Card.Header
				>
				<Card.Content>
					<Field.Set
						><Field.Legend>Cameras that send alerts</Field.Legend><Field.Group>
							{#each cameras as camera (camera.id)}
								<Field.Field orientation="horizontal">
									<Checkbox
										id={`alerts-${camera.id}`}
										checked={cameraIds.includes(camera.id)}
										disabled={pending || !camera.monitored}
										onCheckedChange={(enabled) =>
											(cameraIds = enabled
												? [...cameraIds, camera.id]
												: cameraIds.filter((id) => id !== camera.id))}
									/>
									<Field.Label for={`alerts-${camera.id}`}
										>{camera.label}{!camera.monitored ? ' (view only)' : ''}</Field.Label
									>
								</Field.Field>
							{:else}<Field.Description>Add and monitor a camera first.</Field.Description>{/each}
						</Field.Group></Field.Set
					>
				</Card.Content>
			</Card.Root>
			{#if error}<Alert.Root variant="destructive"
					><Alert.Title>Alerts need attention</Alert.Title><Alert.Description
						>{error}</Alert.Description
					></Alert.Root
				>{/if}
			<div class="flex flex-wrap gap-3">
				<Button type="submit" disabled={pending || connecting || !canSave}
					>{pending
						? 'Saving alerts…'
						: initial
							? 'Save alert settings'
							: 'Enable alerts for selected cameras'}</Button
				>
				<Button href={back} variant="outline">{cameraId ? 'Back to setup' : 'Cancel'}</Button>
			</div>
			{#if initial}<details>
					<summary class="cursor-pointer text-sm text-muted-foreground"
						>Remove this recipient</summary
					>
					<p class="my-3 text-sm">
						Alerts to {label} will stop for every camera. Monitoring and recordings continue.
					</p>
					<Field.Field orientation="horizontal"
						><Checkbox id="remove-recipient" bind:checked={confirmRemove} /><Field.Label
							for="remove-recipient">Stop sending alerts to this recipient</Field.Label
						></Field.Field
					>
					<Button
						class="mt-3"
						type="button"
						variant="destructive"
						disabled={!confirmRemove || pending || connecting}
						onclick={remove}>Remove recipient</Button
					>
				</details>{/if}
		</form>
	{/if}
</section>

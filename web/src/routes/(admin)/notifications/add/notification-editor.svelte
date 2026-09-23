<script lang="ts">
	import { untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { Button, buttonVariants } from '$lib/components/ui/button';
	import { ArrowLeft } from '@lucide/svelte';
	import { Input } from '$lib/components/ui/input';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import * as Field from '$lib/components/ui/field';
	import * as Alert from '$lib/components/ui/alert';
	import * as AlertDialog from '$lib/components/ui/alert-dialog';
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
	let label = $state(untrack(() => initial?.label ?? 'My phone'));
	let token = $state(untrack(() => initial?.token ?? ''));
	let chat = $state(untrack(() => initial?.chat ?? ''));
	let cameraIds = $state(untrack(() => recipientCameraIds(cameras, originalLabel, cameraId)));
	let pending = $state(false);
	let connecting = $state(false);
	let received = $state(false);
	let error = $state('');
	let saved = $state<{ label: string; cameras: string[] }>();
	const connectionUnchanged = $derived(initial && token === initial.token && chat === initial.chat);
	const canSave = $derived(
		label.trim() && cameraIds.length && token && chat && (connectionUnchanged || received)
	);
	const back = $derived(
		cameraId ? resolve(`/setup?camera=${encodeURIComponent(cameraId)}`) : resolve('/notifications')
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

<section class="settings-page">
	<header class="flex flex-col items-start gap-3">
		<Button href={back} variant="ghost" size="sm"
			><ArrowLeft data-icon="inline-start" />{cameraId ? 'Camera setup' : 'Alerts'}</Button
		>
		<h1 class="settings-heading">
			{saved ? 'Alerts are connected' : initial ? 'Manage alerts' : 'Connect alerts'}
		</h1>
		<p class="settings-description">
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
		<form class="settings-layout" onsubmit={save}>
			<div class="flex min-w-0 flex-col gap-6">
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
								placeholder="e.g. My phone"
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
			</div>
			<aside class="settings-aside">
				<div class="flex flex-col gap-2">
					<h2 class="text-sm font-semibold">One recipient, several cameras</h2>
					<p class="text-sm text-muted-foreground">
						Select every camera that should send alerts here. You can reuse this recipient when you
						add more cameras.
					</p>
				</div>
				<div class="flex flex-col gap-2">
					<h2 class="text-sm font-semibold">Check delivery before saving</h2>
					<p class="text-sm text-muted-foreground">
						For a new or changed Telegram connection, send a test message and confirm it arrived on
						your phone.
					</p>
				</div>
				{#if initial}
					<div class="flex flex-col items-start gap-3">
						<h2 class="text-sm font-semibold">Remove this recipient</h2>
						<p class="text-sm text-muted-foreground">
							This stops its alerts for every camera. Monitoring and recordings continue.
						</p>
						<AlertDialog.Root>
							<AlertDialog.Trigger
								type="button"
								class={buttonVariants({ variant: 'outline', size: 'sm' })}
								disabled={pending || connecting}>Remove recipient</AlertDialog.Trigger
							>
							<AlertDialog.Content>
								<AlertDialog.Header
									><AlertDialog.Title>Remove “{originalLabel}”?</AlertDialog.Title
									><AlertDialog.Description
										>Every camera will stop sending alerts to this recipient. Monitoring and saved
										recordings are kept. You can reconnect the recipient later.</AlertDialog.Description
									></AlertDialog.Header
								>
								<AlertDialog.Footer
									><AlertDialog.Cancel type="button">Keep recipient</AlertDialog.Cancel
									><AlertDialog.Action
										type="button"
										class={buttonVariants({ variant: 'destructive' })}
										onclick={remove}>Remove recipient</AlertDialog.Action
									></AlertDialog.Footer
								>
							</AlertDialog.Content>
						</AlertDialog.Root>
					</div>
				{/if}
			</aside>
		</form>
	{/if}
</section>

<script lang="ts">
	import { untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { Button, buttonVariants } from '$lib/components/ui/button';
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
		cameraId = '',
		setupMode = false
	}: {
		originalLabel: string;
		initial?: TelegramMeta;
		cameraId?: string;
		setupMode?: boolean;
	} = $props();
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
	const readyForCameras = $derived(Boolean(connectionUnchanged || received));
	const canSave = $derived(
		label.trim() && cameraIds.length && token && chat && (connectionUnchanged || received)
	);
	const back = $derived(
		resolve(setupMode ? '/setup?step=finish' : cameraId ? '/streams' : '/notifications')
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
		<h1 class="settings-heading">
			{saved ? 'Alerts are connected' : initial ? 'Manage alerts' : 'Connect alerts'}
		</h1>
		<p class="settings-description">
			{saved
				? setupMode
					? 'Return to setup to finish checking your cameras.'
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
		<Button href={back} class="self-start">{setupMode ? 'Back to setup' : 'Done'}</Button>
	{:else}
		<form class="flex max-w-3xl flex-col gap-6" onsubmit={save}>
			<div class="flex min-w-0 flex-col gap-6">
				<Card.Root>
					<Card.Header
						><Card.Title>1. Connect your phone</Card.Title><Card.Description
							>Connect Telegram and confirm that a test alert reaches your phone.</Card.Description
						></Card.Header
					>
					<Card.Content class="flex flex-col gap-5">
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
				{#if readyForCameras}
					<Card.Root>
						<Card.Header
							><Card.Title>2. Choose your cameras</Card.Title><Card.Description
								>{initial
									? 'Existing camera assignments are already selected. Add another camera below.'
									: 'Choose which cameras will send alerts to this recipient.'}</Card.Description
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
									{:else}<Field.Description>Add and monitor a camera first.</Field.Description
										>{/each}
								</Field.Group></Field.Set
							>
						</Card.Content>
					</Card.Root>
				{/if}
				{#if error}<Alert.Root variant="destructive"
						><Alert.Title>Alerts need attention</Alert.Title><Alert.Description
							>{error}</Alert.Description
						></Alert.Root
					>{/if}
				<div class="flex flex-wrap gap-3">
					{#if readyForCameras}<Button type="submit" disabled={pending || connecting || !canSave}
							>{pending
								? 'Saving alerts…'
								: initial
									? 'Save alert settings'
									: 'Enable alerts for selected cameras'}</Button
						>{/if}
					<Button href={back} variant="outline">Cancel</Button>
				</div>
			</div>
			{#if initial}<details>
					<summary class="cursor-pointer text-sm text-muted-foreground">Remove recipient</summary>
					<div class="flex flex-col items-start gap-3">
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
				</details>{/if}
		</form>
	{/if}
</section>

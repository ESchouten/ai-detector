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
	import { getDetectors } from '$lib/remote/detector.remote';
	import { recipientDetectorLabels } from '$lib/alert-recipients';
	import { errorMessage } from '$lib/remote-errors';
	import type { TelegramMeta } from '$lib/schema';
	import TelegramConnection from './telegram-connection.svelte';

	let {
		originalLabel,
		initial,
		detectorLabel = '',
		setupMode = false
	}: {
		originalLabel: string;
		initial?: TelegramMeta;
		detectorLabel?: string;
		setupMode?: boolean;
	} = $props();
	const detectors = await getDetectors();
	let label = $state(untrack(() => initial?.label ?? 'My phone'));
	let token = $state(untrack(() => initial?.token ?? ''));
	let chat = $state(untrack(() => initial?.chat ?? ''));
	let detectorLabels = $state(
		untrack(() => recipientDetectorLabels(detectors, initial, detectorLabel))
	);
	let pending = $state(false);
	let connecting = $state(false);
	let received = $state(false);
	let error = $state('');
	let saved = $state<{ label: string; detectors: string[] }>();
	const connectionUnchanged = $derived(initial && token === initial.token && chat === initial.chat);
	const readyForDetectors = $derived(Boolean(connectionUnchanged || received));
	const canSave = $derived(
		label.trim() && detectorLabels.length && token && chat && (connectionUnchanged || received)
	);
	const back = $derived(
		resolve(setupMode ? '/setup?step=finish' : detectorLabel ? '/detectors' : '/notifications')
	);
	async function save(event: SubmitEvent) {
		event.preventDefault();
		if (!canSave) return;
		pending = true;
		error = '';
		const summary = {
			label,
			detectors: detectorLabels
		};
		try {
			await saveAlerts({
				original: originalLabel || undefined,
				label,
				token,
				chat,
				detectorLabels,
				received
			}).updates(getDetectors(), getTelegrams());
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
			await deleteTelegram({ label: originalLabel }).updates(getDetectors(), getTelegrams());
			await goto(resolve('/notifications'));
		} catch (cause) {
			error = errorMessage(cause, 'Could not remove this recipient.');
		} finally {
			pending = false;
		}
	}
</script>

<section class="settings-page max-w-3xl">
	<header class="flex flex-col items-start gap-2">
		<h1 class="settings-heading">
			{saved ? 'Alerts are connected' : initial ? 'Manage alerts' : 'Connect alerts'}
		</h1>
		<p class="settings-description">
			{saved
				? setupMode
					? 'Return to setup to finish checking your cameras.'
					: 'Your choices are saved. Open alerts to manage your recipients.'
				: initial
					? 'Keep using your saved recipient and choose which detectors send alerts.'
					: 'Connect your phone, confirm a test message, then choose your detectors.'}
		</p>
	</header>
	{#if saved}
		<Alert.Root
			><Alert.Title>{saved.label}</Alert.Title><Alert.Description
				>Alerts are connected to {saved.detectors.join(', ')}.</Alert.Description
			></Alert.Root
		>
		<Button href={back} class="self-start">{setupMode ? 'Back to setup' : 'Done'}</Button>
	{:else}
		<form class="flex flex-col gap-6" onsubmit={save}>
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
				{#if readyForDetectors}
					<Card.Root>
						<Card.Header
							><Card.Title>2. Choose your detectors</Card.Title><Card.Description
								>{initial
									? 'Existing detector assignments are already selected.'
									: 'Choose which detectors send alerts. Each selection includes all of that detector’s cameras.'}</Card.Description
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
								><Field.Legend>Detectors that send alerts</Field.Legend><Field.Group>
									{#each detectors as { meta }, index (meta.label)}
										<Field.Field orientation="horizontal">
											<Checkbox
												id={`alerts-${index}`}
												checked={detectorLabels.includes(meta.label)}
												disabled={pending}
												onCheckedChange={(enabled) =>
													(detectorLabels = enabled
														? [...detectorLabels, meta.label]
														: detectorLabels.filter((id) => id !== meta.label))}
											/>
											<Field.Label for={`alerts-${index}`}>{meta.label}</Field.Label>
										</Field.Field>
									{:else}<Field.Description>Add a detector first.</Field.Description>{/each}
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
					{#if readyForDetectors}<Button type="submit" disabled={pending || connecting || !canSave}
							>{pending
								? 'Saving alerts…'
								: initial
									? 'Save alert settings'
									: 'Enable alerts for selected detectors'}</Button
						>{/if}
					<Button href={back} variant="outline">Cancel</Button>
				</div>
			</div>
			{#if initial}<details>
					<summary class="cursor-pointer text-sm text-muted-foreground">Remove recipient</summary>
					<div class="mt-3 flex flex-col items-start gap-3">
						<p class="text-sm text-muted-foreground">
							This stops its alerts for every detector. Monitoring and recordings continue.
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
										>Every detector will stop sending alerts to this recipient. Monitoring and saved
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

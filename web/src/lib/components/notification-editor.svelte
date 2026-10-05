<script lang="ts">
	import { untrack } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { Button, buttonVariants } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import * as Field from '$lib/components/ui/field';
	import * as Alert from '$lib/components/ui/alert';
	import * as AlertDialog from '$lib/components/ui/alert-dialog';
	import {
		deleteTelegram,
		saveAlerts,
		getTelegrams,
		connectTelegram
	} from '$lib/remote/exporter.remote';
	import { getDetectors } from '$lib/remote/detector.remote';
	import { recipientDetectorLabels } from '$lib/alert-recipients';
	import { sameTelegram } from '$lib/configuration';
	import { errorMessage } from '$lib/remote-errors';
	import type { TelegramMeta } from '$lib/schema';
	import TelegramConnection from './telegram-connection.svelte';

	let {
		originalLabel = '',
		initial,
		inline = false,
		onSaved,
		onCancel
	}: {
		originalLabel?: string;
		inline?: boolean;
		onSaved?: (recipient: TelegramMeta) => void;
		onCancel?: () => void;
		initial?: TelegramMeta;
	} = $props();
	const detectors = await getDetectors();
	const recipients = await getTelegrams();
	let label = $state(untrack(() => initial?.label ?? 'My phone'));
	let token = $state(untrack(() => initial?.token ?? ''));
	let chat = $state(untrack(() => initial?.chat ?? ''));
	let detectorLabels = $state(
		untrack(() =>
			!initial && detectors.length === 1
				? [detectors[0].meta.label]
				: recipientDetectorLabels(detectors, initial)
		)
	);
	let pending = $state(false);
	let connecting = $state(false);
	let received = $state(false);
	let error = $state('');
	const existing = $derived(
		!initial ? recipients.find((recipient) => sameTelegram(recipient, { token, chat })) : undefined
	);
	const connectionUnchanged = $derived(initial && token === initial.token && chat === initial.chat);
	const readyForDetectors = $derived(Boolean(connectionUnchanged || received));
	const canSave = $derived(label.trim() && token && chat && (connectionUnchanged || received));
	const back = resolve('/notifications');
	async function save(event: SubmitEvent) {
		event.preventDefault();
		if (!canSave) return;
		pending = true;
		error = '';
		try {
			if (inline && existing) {
				onSaved?.(existing);
				return;
			}
			await (
				inline
					? connectTelegram({ label, token, chat, received: true })
					: saveAlerts({
							original: originalLabel || existing?.label,
							label: existing?.label ?? label,
							token,
							chat,
							detectorLabels: existing
								? [...new Set([...recipientDetectorLabels(detectors, existing), ...detectorLabels])]
								: detectorLabels,
							received
						})
			).updates(getDetectors(), getTelegrams());
			if (inline) onSaved?.({ label, token, chat });
			else {
				toast.success('Alert settings saved.');
				await goto(back);
			}
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
			await goto(back);
		} catch (cause) {
			error = errorMessage(cause, 'Could not remove this recipient.');
		} finally {
			pending = false;
		}
	}
</script>

<form class="flex flex-col gap-6" onsubmit={save}>
	<div class={inline ? 'flex flex-col gap-5' : 'panel flex flex-col gap-5 p-5'}>
		<TelegramConnection
			{initial}
			bind:token
			bind:chat
			bind:received
			onRecipient={(name) => {
				if (!initial) label = name;
			}}
			bind:busy={connecting}
			disabled={pending}
		/>
	</div>
	{#if readyForDetectors}
		{#if existing}
			<p class="text-sm">
				Already connected as <strong>{existing.label}</strong>. We’ll reuse this recipient.
			</p>
		{:else}
			<Field.Field class="max-w-md">
				<Field.Label for="notification-label">Recipient name</Field.Label>
				<Input
					id="notification-label"
					bind:value={label}
					disabled={pending}
					required
					placeholder="Example: My phone"
				/>
			</Field.Field>
		{/if}
		{#if !inline}
			<Field.Set>
				<Field.Legend>Which detectors alert this recipient?</Field.Legend>
				<Field.Description>Each detector alerts for all of its cameras.</Field.Description>
				<Field.Group class="gap-1">
					{#each detectors as { meta }, index (meta.label)}
						<label
							for={`alerts-${index}`}
							class="-mx-2 flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2 hover:bg-accent"
						>
							<Checkbox
								id={`alerts-${index}`}
								checked={detectorLabels.includes(meta.label)}
								disabled={pending}
								onCheckedChange={(enabled) =>
									(detectorLabels = enabled
										? [...detectorLabels, meta.label]
										: detectorLabels.filter((id) => id !== meta.label))}
							/>
							<span class="text-sm font-medium">{meta.label}</span>
						</label>
					{:else}
						<Field.Description>
							You can connect now and choose this recipient when you add a detector.
						</Field.Description>
					{/each}
				</Field.Group>
			</Field.Set>
		{/if}
	{/if}
	{#if error}
		<Alert.Root variant="destructive">
			<Alert.Title>Alerts need attention</Alert.Title>
			<Alert.Description>{error}</Alert.Description>
		</Alert.Root>
	{/if}
	<div class="flex flex-wrap gap-3">
		{#if readyForDetectors}
			<Button type="submit" disabled={pending || connecting || !canSave}>
				{pending
					? 'Saving…'
					: initial
						? 'Save changes'
						: inline
							? 'Use this recipient'
							: 'Save recipient'}
			</Button>
		{/if}
		{#if inline}
			<Button onclick={onCancel} disabled={pending} variant="outline">Cancel</Button>
		{:else}
			<Button href={back} disabled={pending} variant="outline">Cancel</Button>
		{/if}
	</div>
	{#if initial}
		<div class="border-t pt-5">
			<AlertDialog.Root>
				<AlertDialog.Trigger
					type="button"
					class={buttonVariants({ variant: 'ghost', size: 'sm' }) +
						' -ml-2.5 text-danger-foreground hover:text-danger-foreground'}
					disabled={pending || connecting}>Remove this recipient…</AlertDialog.Trigger
				>
				<AlertDialog.Content>
					<AlertDialog.Header>
						<AlertDialog.Title>Remove “{originalLabel}”?</AlertDialog.Title>
						<AlertDialog.Description>
							Every detector will stop sending alerts to this recipient. Monitoring and saved
							recordings are kept. You can reconnect the recipient later.
						</AlertDialog.Description>
					</AlertDialog.Header>
					<AlertDialog.Footer>
						<AlertDialog.Cancel type="button">Keep recipient</AlertDialog.Cancel>
						<AlertDialog.Action
							type="button"
							class={buttonVariants({ variant: 'destructive' })}
							onclick={remove}>Remove recipient</AlertDialog.Action
						>
					</AlertDialog.Footer>
				</AlertDialog.Content>
			</AlertDialog.Root>
		</div>
	{/if}
</form>

<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { untrack } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import * as Field from '$lib/components/ui/field';
	import * as Alert from '$lib/components/ui/alert';
	import { deleteTelegram, saveTelegram, testTelegram } from '$lib/remote/exporter.remote';
	import type { TelegramMeta } from '$lib/schema';

	let {
		originalLabel,
		initial,
		setupMode
	}: { originalLabel: string; initial?: TelegramMeta; setupMode: boolean } = $props();
	let label = $state(untrack(() => initial?.label ?? ''));
	let token = $state(untrack(() => initial?.token ?? ''));
	let chat = $state(untrack(() => initial?.chat ?? ''));
	let pending = $state(false);
	let testing = $state(false);
	let error = $state('');

	async function remove() {
		pending = true;
		error = '';
		try {
			await deleteTelegram({ label: originalLabel });
			await goto(resolve('/notifications'));
		} catch (cause) {
			error = cause instanceof Error ? cause.message : 'Could not delete this channel.';
		} finally {
			pending = false;
		}
	}

	async function sendTest() {
		testing = true;
		error = '';
		try {
			const result = await testTelegram({ token, chat });
			if (!result.ok) throw new Error(result.description ?? 'Telegram rejected the notification.');
			toast.success('Test notification sent.');
		} catch (cause) {
			error = cause instanceof Error ? cause.message : 'Could not send a test notification.';
		} finally {
			testing = false;
		}
	}
</script>

<section class="flex flex-col gap-6">
	<header class="flex flex-col gap-1">
		<h1 class="text-2xl font-semibold tracking-tight">
			{originalLabel ? 'Edit Telegram channel' : setupMode ? 'Setup: Add Telegram' : 'Add Telegram'}
		</h1>
		<p class="text-sm text-muted-foreground">Add a bot and chat for detector alerts.</p>
	</header>
	<form
		class="flex w-full max-w-lg flex-col gap-6"
		{...saveTelegram.enhance(async ({ submit, data }) => {
			pending = true;
			error = '';
			try {
				await submit();
				if (!saveTelegram.fields.allIssues()?.length) {
					toast.success('Notification channel saved.');
					if (data.next === '/notifications/add?setup=1') {
						label = '';
						token = '';
						chat = '';
					}
				}
			} catch (cause) {
				error = cause instanceof Error ? cause.message : 'Could not save this channel.';
			} finally {
				pending = false;
			}
		})}
	>
		<input type="hidden" name="original" value={originalLabel} />
		<Field.Group>
			<Field.Field data-invalid={Boolean(saveTelegram.fields.label.issues()?.length)}>
				<Field.Label for="notification-label">Label</Field.Label>
				<Input
					id="notification-label"
					name="label"
					bind:value={label}
					required
					disabled={pending}
					aria-invalid={Boolean(saveTelegram.fields.label.issues()?.length)}
					placeholder="e.g. Farm alerts"
				/>
			</Field.Field>
			<Field.Field data-invalid={Boolean(saveTelegram.fields.token.issues()?.length)}>
				<Field.Label for="notification-token">Bot token</Field.Label>
				<Input
					id="notification-token"
					name="token"
					type="password"
					autocomplete="off"
					bind:value={token}
					required
					disabled={pending}
					aria-invalid={Boolean(saveTelegram.fields.token.issues()?.length)}
					placeholder="1234567890:…"
				/>
			</Field.Field>
			<Field.Field data-invalid={Boolean(saveTelegram.fields.chat.issues()?.length)}>
				<Field.Label for="notification-chat">Chat ID</Field.Label>
				<Input
					id="notification-chat"
					name="chat"
					bind:value={chat}
					required
					disabled={pending}
					aria-invalid={Boolean(saveTelegram.fields.chat.issues()?.length)}
					placeholder="e.g. -1234567890"
				/>
			</Field.Field>
			<Button
				type="button"
				variant="outline"
				onclick={sendTest}
				disabled={pending || testing || !token.trim() || !chat.trim()}
				>{testing ? 'Sending…' : 'Test notification'}</Button
			>
		</Field.Group>
		{#if error || saveTelegram.fields.allIssues()?.length}
			<Alert.Root variant="destructive">
				<Alert.Title>Could not update notification</Alert.Title>
				<Alert.Description
					>{error}
					{#each saveTelegram.fields.allIssues() ?? [] as issue, index (index)}
						<p>
							{issue.message}
						</p>
					{/each}
				</Alert.Description>
			</Alert.Root>
		{/if}
		<div class="flex flex-wrap gap-2">
			{#if originalLabel}
				<Button type="button" variant="destructive" onclick={remove} disabled={pending}
					>Delete</Button
				>
			{/if}
			{#if setupMode && !originalLabel}
				<Button
					type="submit"
					name="next"
					value="/notifications/add?setup=1"
					variant="outline"
					disabled={pending}>Save and add another</Button
				>
				<Button type="submit" name="next" value="/setup" disabled={pending}
					>{pending ? 'Saving…' : 'Save and return to setup'}</Button
				>
			{:else}
				<Button type="submit" disabled={pending}>{pending ? 'Working…' : 'Save'}</Button>
			{/if}
		</div>
	</form>
</section>

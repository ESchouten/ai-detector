<script lang="ts">
	import { onDestroy } from 'svelte';
	import { Button } from '$lib/components/ui/button';
	import {
		createTelegramBot,
		pollTelegramBotCreation,
		cancelTelegramBotCreation
	} from '$lib/remote/telegram-manager.remote';
	import { errorMessage } from '$lib/remote-errors';
	let { onCreated, onManual }: { onCreated: (token: string) => void; onManual: () => void } =
		$props();
	let session = $state<Awaited<ReturnType<typeof createTelegramBot>>>();
	let starting = $state(false);
	let error = $state('');
	let generation = 0;
	let timer: ReturnType<typeof setTimeout>;
	function cancel() {
		generation++;
		clearTimeout(timer);
		if (session) void cancelTelegramBotCreation(session.id).catch(() => undefined);
		session = undefined;
	}
	onDestroy(cancel);
	async function poll(attempt: number) {
		if (!session || attempt !== generation) return;
		try {
			if (Date.now() >= session.expiresAt)
				throw new Error('This creation link expired. Create a new one.');
			const result = await pollTelegramBotCreation(session.id);
			if (attempt !== generation) return;
			if (result.state === 'created') {
				cancel();
				onCreated(result.token);
			} else timer = setTimeout(() => void poll(attempt), 2000);
		} catch (cause) {
			if (attempt === generation) {
				error = errorMessage(cause, 'Could not create your bot. Try again.');
				cancel();
			}
		}
	}
	async function start() {
		cancel();
		const attempt = generation;
		starting = true;
		error = '';
		try {
			const created = await createTelegramBot();
			if (attempt !== generation) {
				await cancelTelegramBotCreation(created.id);
				return;
			}
			session = created;
			timer = setTimeout(() => void poll(attempt), 2000);
		} catch (cause) {
			if (attempt === generation)
				error = errorMessage(cause, 'Could not create your bot. Try again.');
		} finally {
			starting = false;
		}
	}
</script>

<div class="flex flex-col items-start gap-3">
	{#if session}
		<p class="text-sm">
			Open Telegram, choose Start, then Create my AI Detector bot. Keep the suggested username.
		</p>
		<img
			src={session.qrDataUrl}
			alt="Scan to create your AI Detector bot in Telegram"
			class="size-48 rounded-md"
		/>
		<Button href={session.url} target="_blank" rel="noreferrer">Open Telegram</Button>
		<p role="status" class="text-sm text-muted-foreground">
			Waiting for your new bot… Return here when Telegram says it is ready.
		</p>
		<Button type="button" variant="outline" onclick={cancel}>Cancel</Button>
	{:else}
		<p class="text-sm text-muted-foreground">
			Create a bot in Telegram without copying a token. The AI Detector manager service connects it
			to this computer.
		</p>
		<Button type="button" disabled={starting} onclick={start}
			>{starting ? 'Preparing…' : 'Create my Telegram bot'}</Button
		>
	{/if}
	{#if error}<p role="alert" class="text-sm text-destructive">{error}</p>{/if}
	<Button
		type="button"
		variant="outline"
		disabled={starting}
		onclick={() => {
			cancel();
			onManual();
		}}>Use a token from BotFather</Button
	>
</div>

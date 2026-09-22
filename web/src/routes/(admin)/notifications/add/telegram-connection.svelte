<script lang="ts">
	import { onDestroy, untrack } from 'svelte';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import * as Alert from '$lib/components/ui/alert';
	import * as Field from '$lib/components/ui/field';
	import * as NativeSelect from '$lib/components/ui/native-select';
	import {
		beginTelegramPairing,
		pollTelegramPairing,
		cancelTelegramPairing,
		discoverTelegramChats,
		testTelegram
	} from '$lib/remote/exporter.remote';
	import { TelegramPairing, type TelegramPairingState } from '$lib/telegram-pairing';
	import type { TelegramRecipient } from '$lib/telegram';
	import { errorMessage } from '$lib/remote-errors';
	import type { TelegramMeta } from '$lib/schema';
	import TelegramBotHelp from './telegram-bot-help.svelte';

	let {
		initial,
		token = $bindable(''),
		chat = $bindable(''),
		received = $bindable(false),
		busy = $bindable(false),
		disabled = false
	}: {
		initial?: TelegramMeta;
		token?: string;
		chat?: string;
		received?: boolean;
		busy?: boolean;
		disabled?: boolean;
	} = $props();
	let editing = $state(untrack(() => !initial));
	let manual = $state(false);
	let pairingState = $state<TelegramPairingState>({ state: 'idle' });
	let chats = $state<TelegramRecipient[]>([]);
	let switching = $state(false);
	let finding = $state(false);
	let testing = $state(false);
	let testSent = $state(false);
	let message = $state('');
	let error = $state('');
	let active = true;
	const pairing = new TelegramPairing(
		{
			begin: beginTelegramPairing,
			poll: pollTelegramPairing,
			cancel: cancelTelegramPairing
		},
		(state) => {
			pairingState = state;
			if (state.state === 'matched') {
				chat = state.chat.id;
				received = false;
				testSent = false;
			}
		}
	);
	$effect(() => {
		busy = disabled || finding || testing || switching || pairingState.state === 'starting';
	});
	onDestroy(() => {
		active = false;
		void pairing.cancel();
	});

	function clearTest() {
		received = false;
		testSent = false;
		error = '';
	}
	function tokenChanged() {
		void pairing.cancel();
		chat = '';
		chats = [];
		message = '';
		clearTest();
	}
	function changeConnection() {
		editing = true;
		tokenChanged();
	}
	async function changeMethod() {
		switching = true;
		await pairing.cancel();
		if (!active) return;
		manual = !manual;
		chat = '';
		chats = [];
		message = '';
		clearTest();
		switching = false;
	}
	function connect() {
		token = token.trim();
		chat = '';
		clearTest();
		void pairing.start(token);
	}
	async function findChats() {
		finding = true;
		error = '';
		try {
			const found = await discoverTelegramChats({ token });
			if (!active) return;
			chats = found;
			message = found.length
				? 'Choose your recipient below.'
				: 'Send a message to your bot, then try again. In a group, mention the bot in your message.';
		} catch (cause) {
			if (active) error = errorMessage(cause, 'Could not find Telegram chats.');
		} finally {
			if (active) finding = false;
		}
	}
	async function sendTest() {
		testing = true;
		clearTest();
		try {
			await testTelegram({ token, chat });
			if (active) testSent = true;
		} catch (cause) {
			if (active)
				error = errorMessage(cause, 'The test could not be sent. Check your bot and recipient.');
		} finally {
			if (active) testing = false;
		}
	}
</script>

<div class="flex flex-col gap-4">
	{#if !editing && initial}
		<p class="text-sm">
			Using the saved Telegram connection for <strong>{initial.label}</strong>. You can change its
			name and cameras without another test.
		</p>
		<Button type="button" variant="outline" disabled={busy} onclick={changeConnection}
			>Change Telegram connection</Button
		>
	{:else}
		<TelegramBotHelp />
		<Field.Field>
			<Field.Label for="notification-token">Bot token from BotFather</Field.Label>
			<Input
				id="notification-token"
				type="password"
				bind:value={token}
				oninput={tokenChanged}
				disabled={busy}
				autocomplete="off"
				required
			/>
			<Field.Description>Already have a bot? Use its existing token.</Field.Description>
		</Field.Field>
		{#if !manual}
			<p class="text-sm text-muted-foreground">
				Use a bot created for AI Detector. For a bot connected to another application, use manual
				setup below.
			</p>
			<Button type="button" variant="outline" disabled={busy || !token.trim()} onclick={connect}
				>{pairingState.state === 'starting' ? 'Checking your bot…' : 'Connect my bot'}</Button
			>
			{#if pairingState.state === 'waiting'}
				<Alert.Root>
					<Alert.Title>{pairingState.session.bot.name} is ready</Alert.Title>
					<Alert.Description
						>Open @{pairingState.session.bot.username} on your phone and choose Start. Keep this page
						open; your phone will appear automatically.</Alert.Description
					>
				</Alert.Root>
				<Button href={pairingState.session.url} target="_blank" rel="noreferrer"
					>Open Telegram</Button
				>
				<img
					src={pairingState.session.qrDataUrl}
					alt={`Scan to connect to ${pairingState.session.bot.name} in Telegram`}
					class="size-48 rounded-md"
				/>
				<p class="text-sm text-muted-foreground" role="status">
					Waiting for you to choose Start in Telegram. This link expires in five minutes.
				</p>
				<Button type="button" variant="outline" onclick={() => pairing.cancel()}
					>Cancel connection</Button
				>
			{:else if pairingState.state === 'matched'}
				<Alert.Root
					><Alert.Title>Phone connected: {pairingState.chat.name}</Alert.Title><Alert.Description
						>Send a test below to check that alerts reach the intended phone.</Alert.Description
					></Alert.Root
				>
			{:else if pairingState.state === 'failed'}
				<Alert.Root variant="destructive"
					><Alert.Title>Connection needs attention</Alert.Title><Alert.Description
						>{pairingState.message}</Alert.Description
					></Alert.Root
				>
			{/if}
		{:else}
			<p class="text-sm text-muted-foreground">
				For a group, add your bot and send a message mentioning it. Find the chat below, or enter a
				known chat ID. Automatic phone matching is paused.
			</p>
			<Button type="button" variant="outline" disabled={busy || !token.trim()} onclick={findChats}
				>{finding ? 'Finding chats…' : 'Find chats'}</Button
			>
			{#if message}<p class="text-sm text-muted-foreground" role="status">{message}</p>{/if}
			{#if chats.length}<Field.Field>
					<Field.Label for="recipient-chat">Send alerts to</Field.Label>
					<NativeSelect.Root
						id="recipient-chat"
						bind:value={chat}
						onchange={clearTest}
						disabled={busy}
					>
						<NativeSelect.Option value="">Choose a recipient</NativeSelect.Option>
						{#each chats as choice (choice.id)}<NativeSelect.Option value={choice.id}
								>{choice.name}</NativeSelect.Option
							>{/each}
					</NativeSelect.Root>
				</Field.Field>{/if}
			<Field.Field
				><Field.Label for="notification-chat">Telegram chat ID</Field.Label><Input
					id="notification-chat"
					bind:value={chat}
					oninput={clearTest}
					disabled={busy}
				/></Field.Field
			>
		{/if}
		<Button type="button" variant="ghost" disabled={busy} onclick={changeMethod}
			>{manual
				? 'Use automatic phone connection'
				: 'Advanced: connect a group or enter a chat ID'}</Button
		>
	{/if}
	{#if chat && token}
		<Button type="button" variant="outline" disabled={busy} onclick={sendTest}
			>{testing ? 'Sending test…' : 'Send test alert'}</Button
		>
	{/if}
	{#if testSent}<Field.Field orientation="horizontal"
			><Checkbox id="alert-received" bind:checked={received} disabled={busy} /><Field.Label
				for="alert-received">I received the test on the intended phone or chat</Field.Label
			></Field.Field
		>{/if}
	{#if error}<Alert.Root variant="destructive"
			><Alert.Title>Alerts need attention</Alert.Title><Alert.Description>{error}</Alert.Description
			></Alert.Root
		>{/if}
</div>

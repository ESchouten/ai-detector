<script lang="ts">
	import { untrack } from 'svelte';
	import { ExternalLink } from '@lucide/svelte';
	import SecretInput from './secret-input.svelte';
	import { Button, buttonVariants } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import * as Field from '$lib/components/ui/field';
	import { resolve } from '$app/paths';
	import * as Alert from '$lib/components/ui/alert';
	import * as AlertDialog from '$lib/components/ui/alert-dialog';
	import { AI_STUDIO_KEYS, GEMINI_MODELS } from '$lib/llm';
	import type { LlmConnection } from '$lib/schema';
	import { errorMessage } from '$lib/remote-errors';
	import {
		saveLlmConnection,
		deleteLlmConnection,
		testLlmConnection,
		getLlmConnections
	} from '$lib/remote/llm.remote';
	import { getDetectors } from '$lib/remote/detector.remote';
	import { uniqueLabel } from '$lib/configuration';
	let {
		initial,
		canTest,
		onSaved,
		onCancel
	}: {
		initial?: LlmConnection;
		canTest: boolean;
		onSaved: (connection: LlmConnection) => void | Promise<void>;
		onCancel: () => void;
	} = $props();
	const connections = await getLlmConnections();
	let label = $state(
		untrack(
			() =>
				initial?.label ??
				uniqueLabel('Google Gemini', new Set(connections.map(({ label }) => label)))
		)
	);
	let key = $state(untrack(() => initial?.key ?? ''));
	const isGemini = $derived(
		!initial ||
			([initial.model].flat().every((model) => model.startsWith('gemini/')) &&
				!initial.url &&
				Boolean(initial.key?.trim()))
	);
	let busy = $state(false);
	let message = $state('');
	let confirmRemove = $state(false);

	async function save(event: SubmitEvent) {
		event.preventDefault();
		busy = true;
		message = '';
		try {
			if (isGemini && !key.trim()) throw new Error('Enter your Google AI Studio API key.');
			const saved = {
				...(initial ?? { model: [...GEMINI_MODELS] }),
				label: label.trim(),
				...(isGemini ? { key: key.trim() } : {})
			};
			if (canTest) await testLlmConnection(saved);
			await saveLlmConnection({ ...saved, original: initial?.label }).updates(
				getLlmConnections(),
				getDetectors()
			);
			await onSaved(saved);
		} catch (cause) {
			message = errorMessage(cause, 'Could not save this connection.');
		} finally {
			busy = false;
		}
	}
	async function remove() {
		if (!initial) return;
		confirmRemove = false;
		busy = true;
		message = '';
		try {
			await deleteLlmConnection(initial.label).updates(getLlmConnections(), getDetectors());
			onCancel();
		} catch (cause) {
			message = errorMessage(cause, 'Could not remove this connection.');
		} finally {
			busy = false;
		}
	}
</script>

<form
	novalidate
	onsubmit={save}
	oninput={() => {
		message = '';
	}}
	class="flex flex-col gap-6"
>
	<Field.Group>
		{#if initial}
			<Field.Field class="max-w-md">
				<Field.Label for="ai-name">Connection name</Field.Label>
				<Input id="ai-name" bind:value={label} required disabled={busy} />
			</Field.Field>
		{/if}
		{#if isGemini}
			<ol class="flex list-decimal flex-col gap-3 pl-5 text-sm leading-relaxed">
				<li>
					Open Google AI Studio and copy or create an API key.
					<Button
						href={AI_STUDIO_KEYS}
						target="_blank"
						rel="noopener noreferrer"
						variant="outline"
						size="sm"
						class="mt-2 flex w-fit"
						>Open Google AI Studio<ExternalLink data-icon="inline-end" aria-hidden="true" /></Button
					>
				</li>
				<li>Paste the key below.</li>
			</ol>
			<Field.Field>
				<Field.Label for="ai-key">API key</Field.Label>
				<SecretInput id="ai-key" name="API key" bind:value={key} required disabled={busy} />
				<Field.Description>
					Kept on this computer. Clips of detected events are sent to Google to be checked.
				</Field.Description>
			</Field.Field>
			<p class="text-sm text-muted-foreground">
				Google offers a limited free tier. Quotas and billing depend on your project. <a
					href="https://ai.google.dev/gemini-api/docs/pricing"
					target="_blank"
					rel="noopener noreferrer"
					class="underline underline-offset-4">Google’s pricing and data-use terms</a
				>.
			</p>
		{:else}
			<p class="text-sm text-muted-foreground">
				This connection uses custom settings. You can edit these in Advanced.
			</p>
			<Button href={resolve('/advanced')} variant="outline" class="self-start">Open Advanced</Button
			>
		{/if}
	</Field.Group>
	<p class="text-sm leading-relaxed text-muted-foreground">
		{canTest
			? 'The key is checked with a test image before it is saved.'
			: 'Connection testing is available in the desktop application. Save settings here for your separate detector.'}
		Detectors waiting for a validator start using this connection. You can turn it off for each detector.
	</p>
	{#if message}
		<Alert.Root variant="destructive">
			<Alert.Title>Connection needs attention</Alert.Title>
			<Alert.Description>{message}</Alert.Description>
		</Alert.Root>
	{/if}
	<div class="flex flex-wrap gap-3">
		<Button type="submit" disabled={busy || (isGemini && !key.trim())}>
			{busy ? 'Connecting…' : canTest ? 'Connect' : 'Save connection'}
		</Button>
		<Button onclick={onCancel} variant="outline" disabled={busy}>Cancel</Button>
	</div>
</form>
{#if initial}
	<div class="mt-6 border-t pt-5">
		<AlertDialog.Root bind:open={confirmRemove}>
			<AlertDialog.Trigger
				class={buttonVariants({ variant: 'ghost', size: 'sm' }) +
					' -ml-2.5 text-danger-foreground hover:text-danger-foreground'}
				disabled={busy}>Remove this connection…</AlertDialog.Trigger
			>
			<AlertDialog.Content>
				<AlertDialog.Header>
					<AlertDialog.Title>Remove {initial.label}?</AlertDialog.Title>
					<AlertDialog.Description>
						Connections assigned to detectors must be unassigned first.
					</AlertDialog.Description>
				</AlertDialog.Header>
				<AlertDialog.Footer>
					<AlertDialog.Cancel>Cancel</AlertDialog.Cancel>
					<AlertDialog.Action class={buttonVariants({ variant: 'destructive' })} onclick={remove}
						>Remove connection</AlertDialog.Action
					>
				</AlertDialog.Footer>
			</AlertDialog.Content>
		</AlertDialog.Root>
	</div>
{/if}

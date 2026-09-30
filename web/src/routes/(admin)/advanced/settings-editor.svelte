<script lang="ts">
	import { beforeNavigate, refreshAll } from '$app/navigation';
	import { tick, untrack } from 'svelte';
	import { Check, RotateCcw, Save } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import * as NativeSelect from '$lib/components/ui/native-select';
	import * as Field from '$lib/components/ui/field';
	import * as Alert from '$lib/components/ui/alert';
	import JsonEditor from '$lib/components/json-editor.svelte';
	import { parseSettings, settingsSchemas, type SettingsDocument } from '$lib/advanced-settings';
	import { errorMessage } from '$lib/remote-errors';
	import { getSettings, saveSettings } from '$lib/remote/settings.remote';

	let { managed }: { managed: boolean } = $props();
	const initial = await getSettings('config');
	let target = $state<SettingsDocument>('config');
	let selected = $state('config');
	let saved = $state(untrack(() => initial));
	let draft = $state(untrack(() => initial.value));
	let busy = $state(false);
	let failure = $state('');
	let message = $state('');
	const dirty = $derived(draft !== saved.value);
	const validation = $derived.by(() => {
		try {
			parseSettings(target, draft);
			return '';
		} catch (cause) {
			return errorMessage(cause, 'Enter valid JSON.');
		}
	});
	const descriptions: Record<SettingsDocument, string> = {
		config:
			'Detector models, prompts, thresholds and recording options in config.json. Saving applies changes to active monitoring.',
		connections:
			'Shared AI connections in app.json. Use a LiteLLM model name, API key, optional URL and headers. Changes apply to assigned detectors. Unassign a connection before removing or renaming it here.',
		runtime:
			'Detection engine in runtime.json: auto, native or docker. Pause monitoring before changing it. The new engine is used the next time monitoring starts.'
	};
	beforeNavigate(({ cancel, willUnload }) => {
		if (dirty && (willUnload || !window.confirm('Discard unsaved JSON changes?'))) cancel();
	});
	async function load(next: SettingsDocument) {
		await tick();
		if (dirty && !window.confirm('Discard unsaved JSON changes?')) {
			selected = target;
			return;
		}
		busy = true;
		failure = '';
		message = '';
		try {
			await getSettings(next).refresh();
			saved = await getSettings(next);
			draft = saved.value;
			target = next;
		} catch (cause) {
			failure = errorMessage(cause, 'Could not load settings.');
		} finally {
			selected = target;
			busy = false;
		}
	}
	async function save() {
		busy = true;
		failure = '';
		message = '';
		try {
			await saveSettings({ target, text: draft, revision: saved.revision }).updates(
				getSettings(target)
			);
			saved = await getSettings(target);
			draft = saved.value;
			message = 'Settings saved.';
			await refreshAll();
		} catch (cause) {
			failure = errorMessage(cause, 'Could not save settings.');
		} finally {
			busy = false;
		}
	}
</script>

<div class="flex min-w-0 flex-col gap-4">
	<Field.Field>
		<Field.Label for="settings-document">Settings</Field.Label>
		<NativeSelect.Root
			id="settings-document"
			bind:value={selected}
			disabled={busy}
			onchange={(event) => {
				const next = event.currentTarget.value as SettingsDocument;
				void load(next);
			}}
		>
			<NativeSelect.Option value="config">Detector configuration</NativeSelect.Option>
			<NativeSelect.Option value="connections">AI connections</NativeSelect.Option>
			{#if managed}<NativeSelect.Option value="runtime">Runtime</NativeSelect.Option>{/if}
		</NativeSelect.Root>
		<Field.Description>{descriptions[target]}</Field.Description>
	</Field.Field>
	{#key target}
		<JsonEditor
			bind:value={draft}
			schema={settingsSchemas[target]}
			height="min(60dvh, 640px)"
			ariaLabel="Advanced settings JSON"
			readonly={busy}
		/>
	{/key}
	{#if validation}<Alert.Root variant="destructive">
			<Alert.Title>Correct the JSON before saving</Alert.Title>
			<Alert.Description
				><p class="break-words whitespace-pre-wrap">{validation}</p></Alert.Description
			>
		</Alert.Root>{/if}
	{#if failure}<Alert.Root variant="destructive"
			><Alert.Title>Settings need attention</Alert.Title><Alert.Description
				>{failure}</Alert.Description
			></Alert.Root
		>{/if}
	<div class="flex flex-wrap items-center gap-3">
		<Button disabled={busy || !dirty || Boolean(validation)} onclick={save}
			><Save data-icon="inline-start" />{busy ? 'Please wait…' : 'Save settings'}</Button
		>
		<Button variant="outline" disabled={busy} onclick={() => load(target)}
			><RotateCcw data-icon="inline-start" />Reload saved</Button
		>
		<p class="flex items-center gap-1.5 text-sm text-muted-foreground" role="status">
			{#if !validation}<Check class="size-4" />{/if}
			{validation
				? 'Invalid JSON'
				: dirty
					? 'Valid JSON · Unsaved changes'
					: message || 'Valid JSON'}
		</p>
	</div>
</div>

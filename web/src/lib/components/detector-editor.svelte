<script lang="ts">
	import { resolve } from '$app/paths';
	import CategoryDot from '$lib/components/category-dot.svelte';
	import { onMount, untrack } from 'svelte';
	import {
		readDetectorChoices,
		writeDetectorChoices,
		type DetectorChoices
	} from '$lib/detector-draft-storage';
	import { toast } from 'svelte-sonner';
	import { Bell, Plus } from '@lucide/svelte';
	import CameraSelection from '$lib/components/camera-selection.svelte';
	import * as Dialog from '$lib/components/ui/dialog';
	import NotificationEditor from '$lib/components/notification-editor.svelte';
	import LlmConnectionEditor from '$lib/components/llm-connection-editor.svelte';
	import DetectorVerification from '$lib/components/detector-verification.svelte';
	import { assignConnection, suggestedConnection } from '$lib/llm';
	import { getLlmConnections, canTestLlm } from '$lib/remote/llm.remote';
	import { Button, buttonVariants } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import * as Field from '$lib/components/ui/field';
	import * as RadioGroup from '$lib/components/ui/radio-group';
	import * as Alert from '$lib/components/ui/alert';
	import * as AlertDialog from '$lib/components/ui/alert-dialog';
	import {
		applyDetectorPreset,
		createDetectorDraft,
		detectorDraftMeta,
		validDetectorDraft,
		selectTelegram
	} from '$lib/detector-editor';
	import { detectorSettings, sameTelegram, uniqueLabel } from '$lib/configuration';
	import { errorMessage } from '$lib/remote-errors';
	import type { DetectorConfig, LlmConnection } from '$lib/schema';
	import {
		deleteDetector,
		getDetectorPreset,
		getDetectors,
		getDetectorPresets,
		saveDetector
	} from '$lib/remote/detector.remote';
	import { getCameras } from '$lib/remote/camera.remote';
	import { getTelegrams } from '$lib/remote/alerts.remote';

	let {
		originalLabel,
		initial,
		initialPreset,
		initialConnection,
		onDone,
		onCancel,
		pending = $bindable(false)
	}: {
		originalLabel: string;
		initial?: DetectorConfig;
		initialPreset?: string;
		initialConnection?: string;
		onDone: () => Promise<void>;
		onCancel?: () => Promise<void>;
		pending?: boolean;
	} = $props();
	// Settings keys this editor by identity; each visit starts a separate draft.
	let label = $state(untrack(() => originalLabel));
	let suggestedLabel = $state('');
	let detector = $state(untrack(() => createDetectorDraft(initial)));
	let llmLabel = $state(untrack(() => initialConnection ?? ''));
	let addingRecipient = $state(false);
	let addingConnection = $state(false);
	const choices = $derived(
		await Promise.all([
			getCameras(),
			getTelegrams(),
			getDetectorPresets(),
			getLlmConnections(),
			canTestLlm(),
			getDetectors()
		])
	);
	const cameras = $derived(choices[0]);
	const telegrams = $derived(choices[1]);
	const presets = $derived(choices[2].presets);
	const presetWarning = $derived(choices[2].warning);
	const llms = $derived(choices[3]);
	const canTest = $derived(choices[4]);
	const existingDetectors = $derived(choices[5]);
	let suggestValidator = $state(untrack(() => !initial));
	let selectedInitialCamera = $state(false);
	$effect(() => {
		if (!selectedInitialCamera) {
			selectedInitialCamera = true;
			if (!initial && cameras.length === 1) detector.detection.source = [cameras[0].source];
		}
	});
	let keepDelivery = $state(untrack(() => Boolean(initial)));
	let error = $state('');
	let preset = $state(untrack(() => initialPreset ?? ''));
	let presetSettings = $state(
		untrack(() => (initial ? JSON.stringify(detectorSettings(initial)) : ''))
	);
	const matchesPreset = $derived(JSON.stringify(detectorSettings(detector)) === presetSettings);
	const selectedPreset = $derived(
		matchesPreset ? presets.find((item) => item.id === preset) : undefined
	);
	const selectedChannels = $derived(detector.exporters.telegram ?? []);
	const draftKey = untrack(() => `detector-draft:${originalLabel || 'new'}`);
	let draftLoaded = $state(false);
	let restoredDraft = $state(false);
	let initialChoices = '';
	function draftChoices(): DetectorChoices {
		// Keep choices only; camera passwords and connection keys stay in server settings.
		return {
			label,
			preset,
			cameras: cameras
				.filter((camera) => detector.detection.source.includes(camera.source))
				.map((camera) => camera.id!),
			telegrams: telegrams
				.filter((channel) => selectedChannels.some((item) => sameTelegram(item, channel)))
				.map((channel) => channel.label),
			connection: llmLabel,
			validatorEnabled: !!detector.vlm?.some((verifier) => verifier.key)
		};
	}

	onMount(() => {
		initialChoices = JSON.stringify(draftChoices());
		async function restore() {
			const draft = readDetectorChoices(draftKey);
			try {
				if (draft) {
					suggestValidator = false;
					if (draft.preset && draft.preset !== initialPreset) await loadPreset(draft.preset);
					label = draft.label;
					detector.detection.source = cameras
						.filter((camera) => draft.cameras.includes(camera.id!))
						.map((camera) => camera.source);
					for (const channel of telegrams)
						detector.exporters.telegram = selectTelegram(
							detector.exporters.telegram ?? [],
							channel,
							draft.telegrams.includes(channel.label)
						);
					keepDelivery = true;
					const connection = llms.find((item) => item.label === draft.connection);
					if (connection) await selectConnection(connection);
					if (!draft.validatorEnabled)
						for (const verifier of detector.vlm ?? []) verifier.key = null;
					restoredDraft = true;
				}
			} catch {
				writeDetectorChoices(draftKey, null);
			} finally {
				draftLoaded = true;
			}
		}
		void restore();
	});
	$effect(() => {
		if (!draftLoaded) return;
		const choices = draftChoices();
		writeDetectorChoices(draftKey, JSON.stringify(choices) === initialChoices ? null : choices);
	});
	function forgetDraft() {
		draftLoaded = false;
		writeDetectorChoices(draftKey, null);
	}

	function showError(cause: unknown, fallback: string) {
		error = errorMessage(cause, fallback);
	}

	function connectionForPreset(next: DetectorConfig) {
		if (!next.vlm?.[0]?.prompt.trim()) return undefined;
		return (
			llms.find(({ label }) => label === llmLabel) ??
			(suggestValidator ? suggestedConnection(next, llms) : undefined)
		);
	}

	async function loadPreset(id: string) {
		if (!id) return;
		const previousName = selectedPreset?.name;
		pending = true;
		error = '';
		try {
			const next = applyDetectorPreset($state.snapshot(detector), await getDetectorPreset({ id }), {
				keepDelivery
			});
			const connection = connectionForPreset(next);
			detector = connection ? assignConnection(next, connection) : next;
			llmLabel = connection?.label ?? '';
			presetSettings = JSON.stringify(detectorSettings(next));
			if (!label || label === previousName || label === suggestedLabel) {
				label = uniqueLabel(
					presets.find((item) => item.id === id)?.name ?? label,
					new Set(
						existingDetectors
							.filter(({ meta }) => meta.label !== originalLabel)
							.map(({ meta }) => meta.label)
					)
				);
				suggestedLabel = label;
			}
			preset = id;
		} catch (cause) {
			showError(cause, 'The preset could not be loaded.');
		} finally {
			pending = false;
		}
	}

	async function selectConnection(connection: LlmConnection) {
		pending = true;
		error = '';
		try {
			const template =
				!detector.vlm?.[0] && selectedPreset
					? await getDetectorPreset({ id: selectedPreset.id })
					: undefined;
			const assigned = assignConnection(detector, connection, template);
			detector = assigned;
			llmLabel = connection.label;
			if (!assigned.vlm[0].prompt.trim()) {
				error = 'Choose a preset to use its AI verification question.';
			}
		} catch (cause) {
			showError(cause, 'Could not load the preset question.');
		} finally {
			pending = false;
		}
	}

	function validateSetup() {
		if (!detector.detection.source.length)
			throw new Error('Choose at least one camera for this detector.');
		if (detector.yolo && !detector.yolo.model.trim())
			throw new Error('Choose a preset for this detector.');
		if (detector.vlm?.some((step) => step.key != null && !step.prompt.trim())) {
			throw new Error('Choose a preset that supplies an AI verification question.');
		}
	}

	async function save() {
		pending = true;
		error = '';
		try {
			validateSetup();
			const valid = validDetectorDraft($state.snapshot(detector));
			const savedLabel = label.trim();
			const connection = llms.find(({ label }) => label === llmLabel);
			await saveDetector({
				original: originalLabel || undefined,
				detector: valid,
				meta: detectorDraftMeta(
					valid,
					savedLabel,
					{ id: preset, settings: presetSettings },
					connection
				)
			}).updates(getDetectors(), getCameras());
			toast.success(`Detector '${savedLabel}' saved.`);
			forgetDraft();
			await onDone();
		} catch (cause) {
			showError(cause, 'The detector could not be saved.');
		} finally {
			pending = false;
		}
	}

	async function remove() {
		pending = true;
		error = '';
		try {
			await deleteDetector({ label: originalLabel }).updates(getDetectors(), getCameras());
			forgetDraft();
			await onDone();
		} catch (cause) {
			showError(cause, 'The detector could not be deleted.');
		} finally {
			pending = false;
		}
	}
</script>

<div class="flex flex-col gap-6">
	{#if restoredDraft}
		<p role="status" class="text-sm text-muted-foreground">
			Your unsaved choices were restored. Review them before saving.
		</p>
	{/if}
	{#if presetWarning}
		<Alert.Root variant="destructive">
			<Alert.Title>Monitoring presets are unavailable</Alert.Title>
			<Alert.Description>
				{presetWarning} You can still edit and save the current configuration.
			</Alert.Description>
		</Alert.Root>
	{/if}
	<form
		class="flex flex-col gap-8"
		onsubmit={(event) => {
			event.preventDefault();
			void save();
		}}
	>
		<Field.Set>
			<Field.Legend>What do you want to detect?</Field.Legend>
			<Field.Description>
				Choose a preset. It supplies everything needed to recognise that kind of event.
			</Field.Description>
			{#if presets.length}
				<RadioGroup.Root
					value={matchesPreset ? preset : ''}
					onValueChange={loadPreset}
					disabled={pending || Boolean(presetWarning)}
					aria-label="Preset"
					class="grid gap-3 sm:grid-cols-2"
				>
					{#each presets as item (item.id)}
						<label
							for={`preset-${item.id}`}
							class="flex cursor-pointer items-center gap-3 rounded-xl border bg-card px-4 py-3.5 transition-colors hover:bg-accent has-disabled:cursor-default has-disabled:opacity-60 has-data-[state=checked]:border-primary has-data-[state=checked]:bg-primary/5"
						>
							<RadioGroup.Item id={`preset-${item.id}`} value={item.id} />
							<span class="min-w-0 flex-1 text-sm font-medium">{item.name}</span>
							<CategoryDot seed={item.id} />
						</label>
					{/each}
				</RadioGroup.Root>
			{/if}
			{#if !selectedPreset && (initial || preset)}
				<p class="text-sm text-muted-foreground">
					This detector uses its own settings, changed in Advanced. Choosing a preset replaces them.
				</p>
			{/if}
		</Field.Set>

		<!-- A new detector is named after its preset; ask only once there is a name to change. -->
		{#if originalLabel || preset || label || presetWarning}
			<Field.Field class="max-w-md">
				<Field.Label for="detector-label">Detector name</Field.Label>
				<Input
					id="detector-label"
					bind:value={label}
					required
					disabled={pending}
					placeholder="Example: Calving pen watch"
				/>
			</Field.Field>
		{/if}

		{#if cameras.length}
			<CameraSelection {cameras} bind:selected={detector.detection.source} disabled={pending} />
		{:else}
			<Alert.Root>
				<Alert.Title>Add a camera first</Alert.Title>
				<Alert.Description>
					A detector watches cameras you have connected.
					<Button href={resolve('/streams/add')} variant="outline" size="sm" class="mt-2">
						<Plus data-icon="inline-start" aria-hidden="true" />Add cameras
					</Button>
				</Alert.Description>
			</Alert.Root>
		{/if}

		<Field.Set>
			<Field.Legend>
				Phone alerts <span class="font-normal text-muted-foreground">(optional)</span>
			</Field.Legend>
			<Field.Description>
				Send a Telegram message with the clip when this detector sees something.
			</Field.Description>
			<Field.Group class="gap-1">
				{#each telegrams as channel, index (channel.label)}
					<label
						for={`channel-${index}`}
						class="-mx-2 flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2 hover:bg-accent"
					>
						<Checkbox
							id={`channel-${index}`}
							disabled={pending}
							checked={selectedChannels.some((item) => sameTelegram(item, channel))}
							onCheckedChange={(checked) => {
								detector.exporters.telegram = selectTelegram(selectedChannels, channel, checked);
								keepDelivery = true;
							}}
						/>
						<span class="text-sm font-medium">{channel.label}</span>
					</label>
				{/each}
			</Field.Group>
			<Button
				variant="outline"
				class="self-start"
				disabled={pending}
				onclick={() => (addingRecipient = true)}
			>
				<Bell data-icon="inline-start" aria-hidden="true" />{telegrams.length
					? 'Connect another phone or group'
					: 'Connect Telegram'}
			</Button>
		</Field.Set>

		<DetectorVerification
			bind:detector
			bind:connectionLabel={llmLabel}
			connections={llms}
			disabled={pending}
			addConnection={() => (addingConnection = true)}
			{selectConnection}
			onChoose={() => (suggestValidator = false)}
		/>

		{#if error}
			<Alert.Root variant="destructive">
				<Alert.Title>Could not update detector</Alert.Title>
				<Alert.Description>{error}</Alert.Description>
			</Alert.Root>
		{/if}
		<div class="flex flex-wrap gap-3">
			<Button type="submit" disabled={pending || !detector.detection.source.length}>
				{pending ? 'Saving…' : 'Save detector'}
			</Button>
			{#if onCancel}
				<Button
					onclick={async () => {
						forgetDraft();
						await onCancel?.();
					}}
					disabled={pending}
					variant="outline">Cancel</Button
				>
			{/if}
		</div>

		{#if originalLabel}
			<div class="border-t pt-5">
				<AlertDialog.Root>
					<AlertDialog.Trigger
						type="button"
						class={buttonVariants({ variant: 'ghost', size: 'sm' }) +
							' -ml-2.5 text-danger-foreground hover:text-danger-foreground'}
						disabled={pending}>Delete this detector…</AlertDialog.Trigger
					>
					<AlertDialog.Content>
						<AlertDialog.Header>
							<AlertDialog.Title>Delete “{originalLabel}”?</AlertDialog.Title>
							<AlertDialog.Description>
								This stops this detector on all of its cameras. Other detectors, camera connections
								and saved recordings are kept. This cannot be undone.
							</AlertDialog.Description>
						</AlertDialog.Header>
						<AlertDialog.Footer>
							<AlertDialog.Cancel type="button">Keep detector</AlertDialog.Cancel>
							<AlertDialog.Action
								type="button"
								class={buttonVariants({ variant: 'destructive' })}
								onclick={remove}>Delete detector</AlertDialog.Action
							>
						</AlertDialog.Footer>
					</AlertDialog.Content>
				</AlertDialog.Root>
			</div>
		{/if}
	</form>
</div>

<Dialog.Root bind:open={addingConnection}>
	<Dialog.Content class="max-h-[90dvh] overflow-y-auto sm:max-w-xl">
		<Dialog.Header>
			<Dialog.Title>Connect validator</Dialog.Title>
			<Dialog.Description>
				Your detector changes stay here until you save the detector.
			</Dialog.Description>
		</Dialog.Header>
		<LlmConnectionEditor
			{canTest}
			onSaved={async (connection) => {
				await selectConnection(connection);
				addingConnection = false;
			}}
			onCancel={() => (addingConnection = false)}
		/>
	</Dialog.Content>
</Dialog.Root>

<Dialog.Root bind:open={addingRecipient}>
	<Dialog.Content class="max-h-[90dvh] overflow-y-auto sm:max-w-xl">
		<Dialog.Header>
			<Dialog.Title>Connect Telegram</Dialog.Title>
			<Dialog.Description>
				Your detector changes stay here until you save the detector.
			</Dialog.Description>
		</Dialog.Header>
		<NotificationEditor
			inline
			onSaved={(recipient) => {
				detector.exporters.telegram = selectTelegram(selectedChannels, recipient, true);
				keepDelivery = true;
				addingRecipient = false;
			}}
			onCancel={() => (addingRecipient = false)}
		/>
	</Dialog.Content>
</Dialog.Root>

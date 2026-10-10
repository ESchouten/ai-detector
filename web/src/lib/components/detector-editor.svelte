<script lang="ts">
	import { resolve } from '$app/paths';
	import CategoryDot from '$lib/components/category-dot.svelte';
	import { onMount, untrack } from 'svelte';
	import { readDetectorChoices, writeDetectorChoices } from '$lib/detector-draft-storage';
	import { toast } from 'svelte-sonner';
	import { Bell, Plus } from '@lucide/svelte';
	import CameraSelection from '$lib/components/camera-selection.svelte';
	import ConfirmRemove from '$lib/components/confirm-remove.svelte';
	import * as Dialog from '$lib/components/ui/dialog';
	import NotificationEditor from '$lib/components/notification-editor.svelte';
	import LlmConnectionEditor from '$lib/components/llm-connection-editor.svelte';
	import DetectorVerification from '$lib/components/detector-verification.svelte';
	import { getLlmConnections, canTestLlm } from '$lib/remote/llm.remote';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Switch } from '$lib/components/ui/switch';
	import * as Field from '$lib/components/ui/field';
	import * as RadioGroup from '$lib/components/ui/radio-group';
	import * as Alert from '$lib/components/ui/alert';
	import {
		chooseConnection,
		choosePreset,
		createDetectorDraft,
		detectorChoices,
		detectorDraftMeta,
		followsPreset,
		lacksQuestion,
		questionPreset,
		restoreDetectorChoices,
		selectTelegram,
		validDetectorDraft,
		type DetectorEdit,
		type DetectorEditProblem,
		type DetectorOptions
	} from '$lib/detector-editor';
	import { detectorSettings, sameTelegram } from '$lib/configuration';
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
		initialAutoUpdate = true,
		initialConnection,
		onDone,
		onCancel,
		pending = $bindable(false)
	}: {
		originalLabel: string;
		initial?: DetectorConfig;
		initialPreset?: string;
		initialAutoUpdate?: boolean;
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
	let autoUpdate = $state(untrack(() => initialAutoUpdate));
	let presetSettings = $state(
		untrack(() => (initial ? JSON.stringify(detectorSettings(initial)) : ''))
	);
	const matchesPreset = $derived(followsPreset(detector, presetSettings));
	const selectedPreset = $derived(
		matchesPreset ? presets.find((item) => item.id === preset) : undefined
	);
	const selectedChannels = $derived(detector.exporters.telegram ?? []);
	const options = $derived<DetectorOptions>({
		cameras,
		telegrams,
		connections: llms,
		presets,
		usedLabels: existingDetectors
			.filter(({ meta }) => meta.label !== originalLabel)
			.map(({ meta }) => meta.label)
	});
	// The rule being edited, as one value for the functions that change it, and back again.
	function edited(): DetectorEdit {
		return {
			label,
			suggestedLabel,
			detector: $state.snapshot(detector),
			preset,
			presetSettings,
			connection: llmLabel
		};
	}
	function show(edit: DetectorEdit) {
		({ label, suggestedLabel, detector, preset, presetSettings } = edit);
		llmLabel = edit.connection;
	}
	const presetDetector = (id: string) => getDetectorPreset({ id });

	const draftKey = untrack(() => `detector-draft:${originalLabel || 'new'}`);
	let draftLoaded = $state(false);
	let restoredDraft = $state(false);
	let initialChoices = '';
	const draftChoices = () =>
		detectorChoices({ label, preset, detector, connection: llmLabel }, { cameras, telegrams });

	onMount(() => {
		initialChoices = JSON.stringify(draftChoices());
		async function restore() {
			const draft = readDetectorChoices(draftKey);
			if (!draft) return;
			suggestValidator = false;
			pending = true;
			try {
				const restored = await restoreDetectorChoices(
					edited(),
					draft,
					options,
					{ savedPreset: initialPreset, keepDelivery },
					presetDetector
				);
				show(restored.edit);
				keepDelivery = true;
				if (restored.problem) showProblem(restored.problem);
				restoredDraft = true;
			} catch {
				writeDetectorChoices(draftKey, null);
			} finally {
				pending = false;
			}
		}
		void restore().finally(() => (draftLoaded = true));
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
	function showProblem(problem: DetectorEditProblem) {
		if (problem.kind === 'no-question')
			error = 'Choose a preset to use its AI verification question.';
		else if (problem.kind === 'preset') showError(problem.cause, 'The preset could not be loaded.');
		else showError(problem.cause, 'Could not load the preset question.');
	}

	async function loadPreset(id: string) {
		if (!id) return;
		pending = true;
		error = '';
		try {
			const chosen = { id, detector: await presetDetector(id) };
			show(
				choosePreset(edited(), chosen, options, {
					keepDelivery,
					suggestConnection: suggestValidator
				})
			);
		} catch (cause) {
			showProblem({ kind: 'preset', cause });
		} finally {
			pending = false;
		}
	}

	async function selectConnection(connection: LlmConnection) {
		pending = true;
		error = '';
		try {
			const template = questionPreset(edited(), presets);
			const question = template ? await presetDetector(template) : undefined;
			show(chooseConnection(edited(), connection, question));
			if (lacksQuestion(detector)) showProblem({ kind: 'no-question' });
		} catch (cause) {
			showProblem({ kind: 'question', cause });
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
					{ id: preset, settings: presetSettings, autoUpdate },
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
			{#if selectedPreset}
				<Field.Field orientation="horizontal">
					<Switch id="detector-auto-update" bind:checked={autoUpdate} disabled={pending} />
					<Field.Content>
						<Field.Label for="detector-auto-update">Update automatically</Field.Label>
						<Field.Description>
							When a newer model is published for this preset, this detector takes it by itself, at
							start and once a day.
						</Field.Description>
					</Field.Content>
				</Field.Field>
			{/if}
			{#if !selectedPreset && (initial || preset)}
				<p class="text-sm text-muted-foreground">
					This detector uses its own settings and does not get new models automatically. Choosing a
					preset replaces them.
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
			<ConfirmRemove
				trigger="Delete this detector…"
				title={`Delete “${originalLabel}”?`}
				description="This stops this detector on all of its cameras. Other detectors, camera connections and saved recordings are kept. This cannot be undone."
				keep="Keep detector"
				confirm="Delete detector"
				disabled={pending}
				onconfirm={remove}
			/>
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

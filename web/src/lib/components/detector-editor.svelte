<script lang="ts">
	import { resolve } from '$app/paths';
	import { untrack } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { Plus } from '@lucide/svelte';
	import CameraSelection from '$lib/components/camera-selection.svelte';
	import * as Dialog from '$lib/components/ui/dialog';
	import NotificationEditor from '$lib/components/notification-editor.svelte';
	import LlmConnectionEditor from '$lib/components/llm-connection-editor.svelte';
	import DetectorVerification from '$lib/components/detector-verification.svelte';
	import { assignConnection } from '$lib/llm';
	import { getLlmConnections, canTestLlm } from '$lib/remote/llm.remote';
	import { Button, buttonVariants } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import * as Field from '$lib/components/ui/field';
	import * as Select from '$lib/components/ui/select';
	import * as Alert from '$lib/components/ui/alert';
	import * as AlertDialog from '$lib/components/ui/alert-dialog';
	import {
		applyDetectorPreset,
		createDetectorDraft,
		detectorDraftMeta,
		parseDetectorDraft,
		selectTelegram
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
	import { getCameras } from '$lib/remote/stream.remote';
	import { getTelegrams } from '$lib/remote/exporter.remote';

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
			canTestLlm()
		])
	);
	const cameras = $derived(choices[0]);
	const telegrams = $derived(choices[1]);
	const presets = $derived(choices[2].presets);
	const presetWarning = $derived(choices[2].warning);
	const llms = $derived(choices[3]);
	const canTest = $derived(choices[4]);
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

	function showError(cause: unknown, fallback: string) {
		error = errorMessage(cause, fallback);
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
			const connection = llms.find(({ label }) => label === llmLabel);
			detector = {
				...(connection ? assignConnection(next, connection) : next),
				vlm_enabled: detector.vlm_enabled
			};
			presetSettings = JSON.stringify(detectorSettings(next));
			if (!label || label === previousName)
				label = presets.find((item) => item.id === id)?.name ?? label;
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
			detector = { ...assigned, vlm_enabled: true };
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
		if (
			detector.vlm_enabled !== false &&
			detector.vlm?.some((step) => step.enabled !== false && !step.prompt.trim())
		) {
			throw new Error('Choose a preset that supplies an AI verification question.');
		}
	}

	async function save() {
		pending = true;
		error = '';
		try {
			validateSetup();
			const valid = parseDetectorDraft(JSON.stringify(detector));
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
			await onDone();
		} catch (cause) {
			showError(cause, 'The detector could not be deleted.');
		} finally {
			pending = false;
		}
	}
</script>

<section class="settings-page">
	<header class="flex flex-col items-start gap-3">
		<div class="flex flex-col gap-2">
			<h1 class="settings-heading">
				{originalLabel ? 'Edit detector' : 'Add detector'}
			</h1>
			<p class="settings-description">
				Choose a preset and select the cameras this detector should watch.
			</p>
		</div>
	</header>
	{#if presetWarning}
		<Alert.Root variant="destructive">
			<Alert.Title>Monitoring presets are unavailable</Alert.Title>
			<Alert.Description
				>{presetWarning} You can still edit and save the current configuration.</Alert.Description
			>
		</Alert.Root>
	{/if}
	<form
		class="flex flex-col gap-6"
		onsubmit={(event) => {
			event.preventDefault();
			void save();
		}}
	>
		<div class="flex min-w-0 flex-col gap-6">
			<div class="flex flex-col gap-6">
				<Field.Group class="grid gap-6 sm:grid-cols-2">
					<Field.Field>
						<Field.Label for="detector-label">Detector name</Field.Label>
						<Input
							id="detector-label"
							bind:value={label}
							required
							disabled={pending}
							placeholder="e.g. Entrance activity"
						/>
					</Field.Field>
					<Field.Field>
						<Field.Label for="detector-preset">Preset</Field.Label>
						<Select.Root
							type="single"
							value={matchesPreset ? preset : ''}
							onValueChange={loadPreset}
							disabled={pending || Boolean(presetWarning)}
						>
							<Select.Trigger id="detector-preset" class="w-full"
								>{selectedPreset?.name ??
									(initial || preset ? 'Current settings' : 'Choose a preset')}</Select.Trigger
							>
							<Select.Content
								><Select.Group>
									{#each presets as item (item.id)}<Select.Item
											value={item.id}
											label={item.name}
										/>{/each}
								</Select.Group></Select.Content
							>
						</Select.Root>
					</Field.Field>
				</Field.Group>
			</div>

			{#if cameras.length}
				<CameraSelection {cameras} bind:selected={detector.detection.source} disabled={pending} />
			{:else}
				<Alert.Root
					><Alert.Title>Add a camera first</Alert.Title><Alert.Description
						>Add and check a camera before selecting it for this detector.</Alert.Description
					></Alert.Root
				>
			{/if}
			{#if !cameras.length}
				<Button href={resolve('/setup?step=cameras')} variant="outline" class="self-start"
					><Plus data-icon="inline-start" />Add cameras</Button
				>{/if}
			<DetectorVerification
				bind:detector
				bind:connectionLabel={llmLabel}
				connections={llms}
				disabled={pending}
				addConnection={() => (addingConnection = true)}
				{selectConnection}
			/>
			<Field.Set>
				<Field.Legend
					>Phone alerts <span class="font-normal text-muted-foreground">(optional)</span
					></Field.Legend
				>
				<Field.Group class="gap-3">
					{#each telegrams as channel, index (channel.label)}
						<Field.Field orientation="horizontal">
							<Checkbox
								id={`channel-${index}`}
								disabled={pending}
								checked={selectedChannels.some((item) => sameTelegram(item, channel))}
								onCheckedChange={(checked) => {
									detector.exporters.telegram = selectTelegram(selectedChannels, channel, checked);
									keepDelivery = true;
								}}
							/>
							<Field.Label for={`channel-${index}`}>{channel.label}</Field.Label>
						</Field.Field>
					{/each}
					<Button
						type="button"
						variant="outline"
						class="self-start"
						disabled={pending}
						onclick={() => (addingRecipient = true)}
						><Plus data-icon="inline-start" />Connect Telegram</Button
					>
				</Field.Group>
			</Field.Set>
			{#if error}<Alert.Root variant="destructive"
					><Alert.Title>Could not update detector</Alert.Title><Alert.Description
						>{error}</Alert.Description
					></Alert.Root
				>{/if}
			<div class="flex flex-wrap gap-3">
				<Button type="submit" disabled={pending || !detector.detection.source.length}
					>{pending ? 'Saving detector…' : 'Save detector'}</Button
				>
				{#if onCancel}<Button type="button" onclick={onCancel} disabled={pending} variant="outline"
						>Cancel</Button
					>{/if}
			</div>
		</div>
		{#if originalLabel}<details>
				<summary class="cursor-pointer text-sm text-muted-foreground">Remove detector</summary>

				<div class="flex flex-col items-start gap-3">
					<p class="text-sm text-muted-foreground">
						Cameras, saved recordings and other detectors are kept.
					</p>
					<AlertDialog.Root>
						<AlertDialog.Trigger
							type="button"
							class={buttonVariants({ variant: 'outline', size: 'sm' })}
							disabled={pending}>Delete detector</AlertDialog.Trigger
						>
						<AlertDialog.Content>
							<AlertDialog.Header
								><AlertDialog.Title>Delete “{originalLabel}”?</AlertDialog.Title
								><AlertDialog.Description
									>This stops this detector on all of its cameras. Other detectors, camera
									connections and saved recordings are kept. This cannot be undone.</AlertDialog.Description
								></AlertDialog.Header
							>
							<AlertDialog.Footer
								><AlertDialog.Cancel type="button">Keep detector</AlertDialog.Cancel
								><AlertDialog.Action
									type="button"
									class={buttonVariants({ variant: 'destructive' })}
									onclick={remove}>Delete detector</AlertDialog.Action
								></AlertDialog.Footer
							>
						</AlertDialog.Content>
					</AlertDialog.Root>
				</div>
			</details>{/if}
	</form>
</section>

<Dialog.Root bind:open={addingConnection}>
	<Dialog.Content class="max-h-[90dvh] overflow-y-auto sm:max-w-xl">
		<Dialog.Header>
			<Dialog.Title>Add AI connection</Dialog.Title>
			<Dialog.Description
				>Your detector changes stay here until you save the detector.</Dialog.Description
			>
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
		<Dialog.Header
			><Dialog.Title>Connect Telegram</Dialog.Title><Dialog.Description
				>Your detector changes stay here until you save the detector.</Dialog.Description
			></Dialog.Header
		>
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

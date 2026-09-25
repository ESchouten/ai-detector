<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { untrack } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { ChevronDown, Plus } from '@lucide/svelte';
	import CameraSelection from '$lib/components/camera-selection.svelte';
	import SetupSteps from '$lib/components/setup-steps.svelte';
	import JsonEditor from '$lib/components/json-editor.svelte';
	import InferenceOptions from '$lib/components/inference-options.svelte';
	import { Button, buttonVariants } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Switch } from '$lib/components/ui/switch';
	import * as Field from '$lib/components/ui/field';
	import * as Select from '$lib/components/ui/select';
	import * as Alert from '$lib/components/ui/alert';
	import * as AlertDialog from '$lib/components/ui/alert-dialog';
	import * as Card from '$lib/components/ui/card';
	import {
		applyDetectorPreset,
		createDetectorDraft,
		parseDetectorDraft,
		selectTelegram
	} from '$lib/detector-editor';
	import { detectorSettings, sameTelegram } from '$lib/configuration';
	import { errorMessage } from '$lib/remote-errors';
	import type { DetectorConfig, TelegramMeta } from '$lib/schema';
	import {
		deleteDetector,
		getDetectorPreset,
		getDetectors,
		getDetectorPresets,
		getDetectorSchema,
		saveDetector
	} from '$lib/remote/detector.remote';
	import { getCameras } from '$lib/remote/stream.remote';
	import { getTelegrams, testTelegram } from '$lib/remote/exporter.remote';

	let {
		originalLabel,
		initial,
		initialPreset,
		setupMode
	}: {
		originalLabel: string;
		initial?: DetectorConfig;
		initialPreset?: string;
		setupMode: boolean;
	} = $props();
	// The route keys this editor by identity; each visit starts a separate draft.
	let label = $state(untrack(() => originalLabel));
	let detector = $state(untrack(() => createDetectorDraft(initial)));
	const choices = $derived(
		await Promise.all([getCameras(), getTelegrams(), getDetectorPresets(), getDetectorSchema()])
	);
	const cameras = $derived(choices[0]);
	const telegrams = $derived(choices[1]);
	const presets = $derived(choices[2].presets);
	const presetWarning = $derived(choices[2].warning);
	const schema = $derived(choices[3]);
	let advanced = $state(false);
	let customize = $state(false);
	let keepDelivery = $state(untrack(() => Boolean(initial)));
	const returnTo = $derived(setupMode ? '/setup?step=detectors' : '/detectors');
	let jsonDraft = $state('');
	let editorHasErrors = $state(false);
	let error = $state('');
	let pending = $state(false);
	let testing = $state<string | null>(null);
	let preset = $state(untrack(() => initialPreset ?? ''));
	let presetSettings = $state(
		untrack(() => (initial ? JSON.stringify(detectorSettings(initial)) : ''))
	);
	const matchesPreset = $derived(JSON.stringify(detectorSettings(detector)) === presetSettings);
	const selectedPreset = $derived(
		matchesPreset ? presets.find((item) => item.id === preset) : undefined
	);
	let previousYolo = $state(untrack(() => detector.yolo));
	const selectedChannels = $derived(detector.exporters.telegram ?? []);

	function showError(cause: unknown, fallback: string) {
		error = errorMessage(cause, fallback);
	}

	function changeAdvanced(enabled: boolean) {
		error = '';
		if (enabled) jsonDraft = JSON.stringify(detector, null, 2);
		else {
			try {
				detector = parseDetectorDraft(jsonDraft);
				previousYolo = detector.yolo;
			} catch (cause) {
				showError(cause, 'Correct the JSON before returning to the form.');
				return;
			}
		}
		advanced = enabled;
	}

	function changeDetection(enabled: boolean) {
		if (enabled) detector.yolo = previousYolo ?? { model: '' };
		else {
			previousYolo = detector.yolo;
			detector.yolo = null;
		}
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
			detector = next;
			presetSettings = JSON.stringify(detectorSettings(next));
			if (!label || label === previousName)
				label = presets.find((item) => item.id === id)?.name ?? label;
			preset = id;
			previousYolo = detector.yolo;
		} catch (cause) {
			showError(cause, 'The preset could not be loaded.');
		} finally {
			pending = false;
		}
	}

	async function save(event: SubmitEvent) {
		event.preventDefault();
		pending = true;
		error = '';
		try {
			if (!advanced && !detector.detection.source.length)
				throw new Error('Choose at least one camera for this detector.');
			if (!advanced && detector.yolo && !detector.yolo.model.trim())
				throw new Error('Choose a preset, or enter a model in the custom settings.');
			const valid = parseDetectorDraft(advanced ? jsonDraft : JSON.stringify(detector));
			await saveDetector({
				original: originalLabel || undefined,
				detector: valid,
				meta: {
					label,
					preset:
						preset && JSON.stringify(detectorSettings(valid)) === presetSettings
							? preset
							: undefined
				}
			}).updates(getDetectors(), getCameras());
			toast.success(`Detector '${label}' saved.`);
			await goto(resolve(returnTo));
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
			await goto(resolve(returnTo));
		} catch (cause) {
			showError(cause, 'The detector could not be deleted.');
		} finally {
			pending = false;
		}
	}

	async function testChannel(channel: TelegramMeta) {
		testing = channel.label;
		try {
			const result = await testTelegram({ token: channel.token, chat: channel.chat });
			if (!result.ok)
				throw new Error(result.description ?? 'Telegram rejected the test notification.');
			toast.success('Test notification sent.');
		} catch (cause) {
			toast.error(errorMessage(cause, 'Could not send a test notification.'));
		} finally {
			testing = null;
		}
	}

	async function refreshChoices() {
		if (document.visibilityState !== 'visible') return;
		try {
			await Promise.all([getCameras().refresh(), getTelegrams().refresh()]);
		} catch {
			toast.error('Could not refresh cameras and alert recipients.');
		}
	}
</script>

<svelte:document onvisibilitychange={refreshChoices} />

<section class="settings-page">
	{#if setupMode}<SetupSteps
			current="detectors"
			hasCameras={cameras.length > 0}
			disabled={pending}
		/>{/if}
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
	<form class="flex max-w-4xl flex-col gap-6" onsubmit={save}>
		<div class="flex min-w-0 flex-col gap-6">
			<div class="flex flex-col gap-5">
				<Field.Group class={advanced ? '' : 'grid gap-6 sm:grid-cols-2'}>
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
					{#if !advanced}
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
					{/if}
				</Field.Group>
				{#if customize}<Field.Field class="mt-5">
						<div class="flex items-center gap-3">
							<Switch
								id="detector-advanced"
								bind:checked={() => advanced, changeAdvanced}
								disabled={pending}
							/><Field.Label for="detector-advanced">Advanced JSON</Field.Label>
						</div>
						<Field.Description
							>Access every setting for this detector, including validation and delivery. The
							configuration is checked before saving.</Field.Description
						>
					</Field.Field>{/if}
			</div>
			{#if advanced}
				<Card.Root>
					<Card.Header>
						<Card.Title>Detector configuration</Card.Title>
						<Card.Description
							>Edit this detector's complete configuration. Changes stay in this draft until you
							save.</Card.Description
						>
					</Card.Header>
					<Card.Content class="flex min-w-0 flex-col gap-4">
						<JsonEditor
							bind:value={jsonDraft}
							bind:hasErrors={editorHasErrors}
							{schema}
							height={520}
							ariaLabel="Detector JSON"
						/>
						<Button
							type="button"
							variant="outline"
							class="self-start"
							disabled={pending}
							onclick={() => {
								advanced = false;
								error = '';
								editorHasErrors = false;
							}}>Discard JSON changes</Button
						>
					</Card.Content>
				</Card.Root>
			{:else}
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
					<Button
						href={resolve(setupMode ? '/setup?step=cameras' : '/streams/add')}
						variant="outline"
						class="self-start"><Plus data-icon="inline-start" />Add cameras</Button
					>{/if}
				<Button
					type="button"
					variant="outline"
					class="self-start"
					disabled={pending}
					aria-expanded={customize}
					onclick={() => {
						customize = !customize;
						keepDelivery = true;
					}}
				>
					{customize ? 'Hide advanced settings' : 'Advanced settings'}
					<ChevronDown data-icon="inline-end" class={customize ? 'rotate-180' : ''} /></Button
				>
				{#if customize}
					<Card.Root>
						<Card.Header
							><Card.Title>Detection</Card.Title><Card.Description
								>Use the preset defaults, or adjust how this detector recognizes objects.</Card.Description
							></Card.Header
						>
						<Card.Content>
							<Field.Group>
								<Field.Field orientation="horizontal">
									<Switch
										id="object-detection"
										checked={Boolean(detector.yolo)}
										onCheckedChange={changeDetection}
										disabled={pending}
									/>
									<Field.Label for="object-detection">Object detection</Field.Label>
								</Field.Field>
								{#if detector.yolo}
									<Field.Field>
										<Field.Label for="detector-model">Model</Field.Label>
										<Input
											id="detector-model"
											bind:value={detector.yolo.model}
											placeholder="Model name, file path or URL"
											required
											disabled={pending}
										/>
									</Field.Field>
									{#if typeof detector.yolo.confidence !== 'object'}
										<Field.Field>
											<Field.Label for="detector-confidence">Confidence threshold</Field.Label>
											<Input
												id="detector-confidence"
												type="number"
												min="0"
												max="1"
												step="0.01"
												bind:value={detector.yolo.confidence}
												placeholder="Default: 0"
												disabled={pending}
											/>
											<Field.Description
												>A value from 0 to 1. Higher values require more confident detections.</Field.Description
											>
										</Field.Field>
									{:else}
										<Field.Set>
											<Field.Legend>Confidence per class</Field.Legend>
											<Field.Group class="grid grid-cols-1 sm:grid-cols-2">
												{#each Object.keys(detector.yolo.confidence) as name (name)}
													<Field.Field
														><Field.Label for={`confidence-${name}`}>{name}</Field.Label><Input
															id={`confidence-${name}`}
															type="number"
															min="0"
															max="1"
															step="0.01"
															bind:value={detector.yolo.confidence[name]}
															disabled={pending}
														/></Field.Field
													>
												{/each}
											</Field.Group>
										</Field.Set>
									{/if}
									<Field.Field>
										<Field.Label for="detector-frames">Required detected frames</Field.Label>
										<Input
											id="detector-frames"
											type="number"
											min="1"
											step="1"
											bind:value={detector.yolo.frames_min}
											placeholder="Default: 3"
											disabled={pending}
										/>
										<Field.Description
											>Minimum number of matching frames before an event is accepted.</Field.Description
										>
									</Field.Field>
									<InferenceOptions yolo={detector.yolo} disabled={pending} />
								{:else}
									<Field.Description
										>Snapshot mode processes sampled frames without object detection. Delivery
										settings below still apply.</Field.Description
									>
								{/if}
							</Field.Group>
						</Card.Content>
					</Card.Root>
					<Card.Root>
						<Card.Header
							><Card.Title>Delivery</Card.Title><Card.Description
								>Choose which saved Telegram recipients receive events from this detector.</Card.Description
							></Card.Header
						>
						<Card.Content class="flex flex-col gap-5">
							<Field.Set>
								<Field.Legend class="sr-only">Telegram recipients</Field.Legend>
								<Field.Group>
									{#each telegrams as channel, index (channel.label)}
										{@const exporter = selectedChannels.find((item) => sameTelegram(item, channel))}
										<Field.Field>
											<div class="flex flex-wrap items-center gap-3">
												<Checkbox
													id={`channel-${index}`}
													checked={Boolean(exporter)}
													onCheckedChange={(checked) => {
														detector.exporters.telegram = selectTelegram(
															selectedChannels,
															channel,
															checked
														);
													}}
													disabled={pending}
												/>
												<Field.Label for={`channel-${index}`}>{channel.label}</Field.Label>
												<Button
													type="button"
													variant="outline"
													size="sm"
													onclick={() => testChannel(channel)}
													disabled={testing !== null || pending}
													>{testing === channel.label ? 'Sending…' : 'Send test message'}</Button
												>
											</div>
											{#if exporter}
												<Field.Field>
													<Field.Label for={`alert-${index}`}>Notification sound every</Field.Label>
													<div class="flex items-center gap-3">
														<Input
															id={`alert-${index}`}
															class="w-24"
															type="number"
															min="1"
															step="1"
															bind:value={exporter.alert_every}
															placeholder="1"
															disabled={pending}
														/><span class="text-sm text-muted-foreground">events</span>
													</div>
													<Field.Description
														>Every event is sent. Other messages arrive silently; leave blank for
														sound on every event.</Field.Description
													>
												</Field.Field>
											{/if}
										</Field.Field>
									{:else}
										<Field.Description
											>No Telegram recipients yet. Local monitoring works without alerts.</Field.Description
										>
									{/each}
								</Field.Group>
							</Field.Set>
							<Button
								href={resolve(setupMode ? '/notifications/add?setup=1' : '/notifications/add')}
								target="_blank"
								rel="noopener"
								variant="outline"
								class="self-start"><Plus data-icon="inline-start" /> Connect alert recipient</Button
							>
							<p class="text-sm text-muted-foreground">
								Recording destinations, webhooks and other delivery options are available in
								Advanced JSON.
							</p>
						</Card.Content>
					</Card.Root>
				{/if}
			{/if}
			{#if error}<Alert.Root variant="destructive"
					><Alert.Title>Could not update detector</Alert.Title><Alert.Description
						>{error}</Alert.Description
					></Alert.Root
				>{/if}
			<div class="flex flex-wrap gap-3">
				<Button
					type="submit"
					disabled={pending || (advanced ? editorHasErrors : !detector.detection.source.length)}
					>{pending ? 'Saving detector…' : 'Save detector'}</Button
				>
				<Button href={resolve(returnTo)} variant="outline">Cancel</Button>
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

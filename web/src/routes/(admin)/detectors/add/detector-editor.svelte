<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { untrack } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { ArrowLeft, Plus } from '@lucide/svelte';
	import CameraPicture from '$lib/components/camera-picture.svelte';
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
	import { sameTelegram } from '$lib/configuration';
	import { errorMessage } from '$lib/remote-errors';
	import type { DetectorConfig, TelegramMeta } from '$lib/schema';
	import {
		deleteDetector,
		getDetectorPreset,
		getDetectorPresets,
		getDetectorSchema,
		saveDetector
	} from '$lib/remote/detector.remote';
	import { getCameras } from '$lib/remote/stream.remote';
	import { getTelegrams, testTelegram } from '$lib/remote/exporter.remote';

	let {
		originalLabel,
		initial,
		setupMode
	}: { originalLabel: string; initial?: DetectorConfig; setupMode: boolean } = $props();
	// The route keys this editor by identity; each visit starts a separate draft.
	let label = $state(untrack(() => originalLabel));
	let detector = $state(untrack(() => createDetectorDraft(initial)));
	const cameras = $derived(await getCameras());
	const telegrams = $derived(await getTelegrams());
	const { catalogue, warning: catalogueWarning } = await getDetectorPresets();
	const schema = await getDetectorSchema();
	let advanced = $state(false);
	let jsonDraft = $state('');
	let editorHasErrors = $state(false);
	let error = $state('');
	let pending = $state(false);
	let testing = $state<string | null>(null);
	let preset = $state('');
	const selectedPreset = $derived(catalogue.presets.find((item) => item.id === preset));
	let previousYolo = $state(untrack(() => detector.yolo));
	const selectedChannels = $derived(detector.exporters.telegram ?? []);
	const selectedCameras = $derived(
		cameras.filter((camera) => detector.detection.source.includes(camera.source))
	);
	const sources = $derived([
		...cameras,
		...detector.detection.source
			.filter((source) => !cameras.some((item) => item.source === source))
			.map((source) => ({ source, label: source }))
	]);

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
		pending = true;
		error = '';
		try {
			detector = applyDetectorPreset(detector, await getDetectorPreset({ id }));
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
			const valid = parseDetectorDraft(advanced ? jsonDraft : JSON.stringify(detector));
			await saveDetector({
				original: originalLabel || undefined,
				detector: valid,
				meta: { label }
			});
			toast.success(`Monitoring rule '${label}' saved.`);
			await goto(resolve(setupMode ? '/setup?complete=1' : '/detectors'));
		} catch (cause) {
			showError(cause, 'The monitoring rule could not be saved.');
		} finally {
			pending = false;
		}
	}

	async function remove() {
		pending = true;
		error = '';
		try {
			await deleteDetector({ label: originalLabel });
			await goto(resolve('/detectors'));
		} catch (cause) {
			showError(cause, 'The monitoring rule could not be deleted.');
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
	<header class="flex flex-col items-start gap-3">
		<Button href={resolve('/detectors')} variant="ghost" size="sm"
			><ArrowLeft data-icon="inline-start" /> Monitoring rules</Button
		>
		<div class="flex flex-col gap-2">
			<h1 class="settings-heading">
				{originalLabel ? 'Edit monitoring rule' : 'Add monitoring rule'}
			</h1>
			<p class="settings-description">
				Choose what to detect, which cameras to watch and where to send results.
			</p>
		</div>
	</header>
	{#if catalogueWarning}
		<Alert.Root variant="destructive">
			<Alert.Title>Monitoring presets are unavailable</Alert.Title>
			<Alert.Description
				>{catalogueWarning} You can still edit and save the current configuration.</Alert.Description
			>
		</Alert.Root>
	{/if}
	<form class="settings-layout" onsubmit={save}>
		<div class="flex min-w-0 flex-col gap-6">
			<Card.Root>
				<Card.Header>
					<Card.Title>Rule details</Card.Title>
					<Card.Description
						>One rule can watch one camera or several cameras with the same settings.</Card.Description
					>
				</Card.Header>
				<Card.Content>
					<Field.Group class={advanced ? '' : 'grid gap-6 sm:grid-cols-2'}>
						<Field.Field>
							<Field.Label for="detector-label">Rule name</Field.Label>
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
									value={preset}
									onValueChange={loadPreset}
									disabled={pending || Boolean(catalogueWarning)}
								>
									<Select.Trigger id="detector-preset" class="w-full"
										>{selectedPreset?.name ?? 'Custom configuration'}</Select.Trigger
									>
									<Select.Content
										><Select.Group>
											{#each catalogue.presets as item (item.id)}<Select.Item
													value={item.id}
													label={item.name}
												/>{/each}
										</Select.Group></Select.Content
									>
								</Select.Root>
								<Field.Description
									>Loading a preset replaces detection settings. Your selected cameras and delivery
									settings stay.</Field.Description
								>
							</Field.Field>
						{/if}
					</Field.Group>
					{#if !advanced && selectedPreset}
						<div class="mt-5 flex flex-col gap-2 text-sm text-muted-foreground">
							<p>{selectedPreset.description}</p>
							{#if selectedPreset.guidance}<p>{selectedPreset.guidance}</p>{/if}
						</div>
					{/if}
					<Field.Field class="mt-5">
						<div class="flex items-center gap-3">
							<Switch
								id="detector-advanced"
								bind:checked={() => advanced, changeAdvanced}
								disabled={pending}
							/><Field.Label for="detector-advanced">Advanced JSON</Field.Label>
						</div>
						<Field.Description
							>Access every setting for this rule, including validation and delivery. The
							configuration is checked before saving.</Field.Description
						>
					</Field.Field>
				</Card.Content>
			</Card.Root>
			{#if advanced}
				<Card.Root>
					<Card.Header>
						<Card.Title>Rule configuration</Card.Title>
						<Card.Description
							>Edit this rule's complete configuration. Changes stay in this draft until you save.</Card.Description
						>
					</Card.Header>
					<Card.Content class="flex min-w-0 flex-col gap-4">
						<JsonEditor
							bind:value={jsonDraft}
							bind:hasErrors={editorHasErrors}
							{schema}
							height={520}
							ariaLabel="Monitoring rule JSON"
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
				<Card.Root>
					<Card.Header>
						<Card.Title>Cameras</Card.Title>
						<Card.Description
							>All selected cameras use this rule. Other rules on those cameras stay separate.</Card.Description
						>
					</Card.Header>
					<Card.Content class="flex flex-col gap-5">
						<Field.Field>
							<Field.Label for="detector-sources">Cameras and sources</Field.Label>
							<div class="flex gap-2">
								<Select.Root
									type="multiple"
									bind:value={detector.detection.source}
									disabled={pending}
								>
									<Select.Trigger id="detector-sources" class="w-full min-w-0"
										>{detector.detection.source.length
											? `${detector.detection.source.length} selected`
											: 'Select cameras or sources'}</Select.Trigger
									>
									<Select.Content
										><Select.Group>
											{#each sources as source (source.source)}
												<Select.Item value={source.source} label={source.label ?? source.source}
													>{source.label ?? source.source}</Select.Item
												>
											{/each}
										</Select.Group></Select.Content
									>
								</Select.Root>
								<Button
									href={resolve(setupMode ? '/streams/add?setup=1' : '/streams/add')}
									target="_blank"
									rel="noopener"
									variant="outline"
									size="icon"
									aria-label="Add camera in a new tab"><Plus /></Button
								>
							</div>
							<Field.Description
								>Select at least one source. Add and manage camera connections on the <a
									href={resolve('/streams')}>Cameras page</a
								>.</Field.Description
							>
						</Field.Field>
						{#if selectedCameras.length}
							<div class="grid gap-4 sm:grid-cols-2">
								{#each selectedCameras as camera (camera.id)}
									<div class="flex min-w-0 flex-col gap-3 rounded-lg border p-4">
										<p class="text-sm font-medium">{camera.label}</p>
										<CameraPicture
											id={camera.id}
											label={camera.label}
											monitored={camera.monitored}
										/>
									</div>
								{/each}
							</div>
						{/if}
					</Card.Content>
				</Card.Root>
				<Card.Root>
					<Card.Header
						><Card.Title>Detection</Card.Title><Card.Description
							>Use the preset defaults, or adjust how this rule recognizes objects.</Card.Description
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
							>Choose which saved Telegram recipients receive events from this rule.</Card.Description
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
							Recording destinations, webhooks and other delivery options are available in Advanced
							JSON.
						</p>
					</Card.Content>
				</Card.Root>
			{/if}
			{#if error}<Alert.Root variant="destructive"
					><Alert.Title>Could not update monitoring rule</Alert.Title><Alert.Description
						>{error}</Alert.Description
					></Alert.Root
				>{/if}
			<div class="flex flex-wrap gap-3">
				<Button type="submit" disabled={pending || (advanced && editorHasErrors)}
					>{pending ? 'Working…' : 'Save monitoring rule'}</Button
				>
				<Button href={resolve('/detectors')} variant="outline">Cancel</Button>
			</div>
		</div>
		<aside class="settings-aside">
			<div class="flex flex-col gap-2">
				<h2 class="text-sm font-semibold">Start with a preset</h2>
				<p class="text-sm text-muted-foreground">
					A preset provides a model and detection settings. You can keep its defaults or customize
					this rule.
				</p>
			</div>
			<div class="flex flex-col gap-2">
				<h2 class="text-sm font-semibold">More than one kind of detection?</h2>
				<p class="text-sm text-muted-foreground">
					Create another rule for the same camera. Loading a different preset here replaces this
					rule's detection settings.
				</p>
			</div>
			{#if originalLabel}
				<div class="flex flex-col items-start gap-3">
					<h2 class="text-sm font-semibold">Remove this rule</h2>
					<p class="text-sm text-muted-foreground">
						Cameras, saved recordings and other monitoring rules are kept.
					</p>
					<AlertDialog.Root>
						<AlertDialog.Trigger
							type="button"
							class={buttonVariants({ variant: 'outline', size: 'sm' })}
							disabled={pending}>Delete rule</AlertDialog.Trigger
						>
						<AlertDialog.Content>
							<AlertDialog.Header
								><AlertDialog.Title>Delete “{originalLabel}”?</AlertDialog.Title
								><AlertDialog.Description
									>This stops this rule on all of its cameras. Other monitoring rules, camera
									connections and saved recordings are kept. This cannot be undone.</AlertDialog.Description
								></AlertDialog.Header
							>
							<AlertDialog.Footer
								><AlertDialog.Cancel type="button">Keep rule</AlertDialog.Cancel><AlertDialog.Action
									type="button"
									class={buttonVariants({ variant: 'destructive' })}
									onclick={remove}>Delete rule</AlertDialog.Action
								></AlertDialog.Footer
							>
						</AlertDialog.Content>
					</AlertDialog.Root>
				</div>
			{/if}
		</aside>
	</form>
</section>

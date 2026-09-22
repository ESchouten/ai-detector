<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { untrack } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { Plus } from '@lucide/svelte';
	import JsonEditor from '$lib/components/json-editor.svelte';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Switch } from '$lib/components/ui/switch';
	import * as Field from '$lib/components/ui/field';
	import * as Select from '$lib/components/ui/select';
	import * as Alert from '$lib/components/ui/alert';
	import {
		applyDetectorPreset,
		createDetectorDraft,
		parseDetectorDraft,
		selectTelegram
	} from '$lib/detector-editor';
	import { sameTelegram } from '$lib/configuration';
	import type { DetectorConfig, TelegramMeta } from '$lib/schema';
	import {
		deleteDetector,
		getDetectorPreset,
		getDetectorPresets,
		getDetectorSchema,
		saveDetector
	} from '$lib/remote/detector.remote';
	import { getStreams } from '$lib/remote/stream.remote';
	import { getTelegrams, testTelegram } from '$lib/remote/exporter.remote';

	let {
		originalLabel,
		initial,
		setupMode
	}: { originalLabel: string; initial?: DetectorConfig; setupMode: boolean } = $props();
	// The route keys this editor by identity; each visit starts a separate draft.
	let label = $state(untrack(() => originalLabel));
	let detector = $state(untrack(() => createDetectorDraft(initial)));
	const streams = $derived(await getStreams());
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
	const sources = $derived([
		...streams,
		...detector.detection.source
			.filter((source) => !streams.some((item) => item.source === source))
			.map((source) => ({ source, label: source }))
	]);

	function showError(cause: unknown, fallback: string) {
		error = cause instanceof Error ? cause.message : fallback;
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
			toast.success(`Detector '${label}' saved.`);
			await goto(resolve(setupMode ? '/setup?complete=1' : '/detectors'));
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
			await deleteDetector({ label: originalLabel });
			await goto(resolve('/detectors'));
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
			toast.error(cause instanceof Error ? cause.message : 'Could not send a test notification.');
		} finally {
			testing = null;
		}
	}

	async function refreshChoices() {
		if (document.visibilityState !== 'visible') return;
		try {
			await Promise.all([getStreams().refresh(), getTelegrams().refresh()]);
		} catch {
			toast.error('Could not refresh streams and notifications.');
		}
	}
</script>

<svelte:document onvisibilitychange={refreshChoices} />

<section class="flex min-w-0 flex-col gap-6">
	<header class="flex flex-col gap-1">
		<h1 class="text-2xl font-semibold tracking-tight">
			{originalLabel ? 'Edit detector' : setupMode ? 'Setup: Add detector' : 'Add detector'}
		</h1>
		<p class="text-sm text-muted-foreground">
			Choose sources, detection rules and notification channels.
		</p>
	</header>
	{#if catalogueWarning}
		<Alert.Root variant="destructive">
			<Alert.Title>Monitoring presets are unavailable</Alert.Title>
			<Alert.Description>
				{catalogueWarning} You can still edit and save the current configuration.
			</Alert.Description>
		</Alert.Root>
	{/if}
	<form class="flex w-full max-w-2xl min-w-0 flex-col gap-6" onsubmit={save}>
		<Field.Group>
			<Field.Field>
				<Field.Label for="detector-label">Label</Field.Label>
				<Input
					id="detector-label"
					bind:value={label}
					required
					disabled={pending}
					placeholder="e.g. Front entrance"
				/>
			</Field.Field>
			<Field.Field orientation="horizontal">
				<Switch
					id="detector-advanced"
					checked={advanced}
					onCheckedChange={changeAdvanced}
					disabled={pending}
				/>
				<Field.Label for="detector-advanced">Advanced JSON</Field.Label>
			</Field.Field>
		</Field.Group>
		{#if advanced}
			<Field.Field>
				<Field.Title>Detector configuration</Field.Title>
				<Field.Description>Changes stay in this draft until they pass validation.</Field.Description
				>
				<JsonEditor bind:value={jsonDraft} bind:hasErrors={editorHasErrors} {schema} height={420} />
				<Button
					type="button"
					variant="outline"
					disabled={pending}
					onclick={() => {
						advanced = false;
						error = '';
						editorHasErrors = false;
					}}>Discard JSON changes</Button
				>
			</Field.Field>
		{:else}
			<Field.Group>
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
						<Select.Content>
							<Select.Group>
								{#each catalogue.presets as item (item.id)}
									<Select.Item value={item.id} label={item.name} />
								{/each}
							</Select.Group>
						</Select.Content>
					</Select.Root>
					{#if selectedPreset}<Field.Description>{selectedPreset.description}</Field.Description
						>{/if}
					{#if selectedPreset?.guidance}<Field.Description
							>{selectedPreset.guidance}</Field.Description
						>{/if}
				</Field.Field>
				<Field.Field>
					<Field.Label for="detector-sources">Sources</Field.Label>
					<div class="flex gap-2">
						<Select.Root type="multiple" bind:value={detector.detection.source} disabled={pending}>
							<Select.Trigger id="detector-sources" class="w-full min-w-0"
								>{detector.detection.source.length
									? `${detector.detection.source.length} source(s) selected`
									: 'Select sources'}</Select.Trigger
							>
							<Select.Content>
								<Select.Group>
									{#each sources as source (source.source)}
										<Select.Item value={source.source} label={source.label ?? source.source}
											>{source.label ?? source.source}</Select.Item
										>
									{/each}
								</Select.Group>
							</Select.Content>
						</Select.Root>
						<Button
							href={setupMode ? '/streams/add?setup=1' : '/streams/add'}
							target="_blank"
							rel="noopener"
							variant="outline"
							aria-label="Add source"
						>
							<Plus />
						</Button>
					</div>
					<Field.Description>Preview and manage cameras on the Streams page.</Field.Description>
				</Field.Field>
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
							placeholder="Model name or file path"
							required
							disabled={pending}
						/>
					</Field.Field>
					{#if typeof detector.yolo.confidence !== 'object'}
						<Field.Field>
							<Field.Label for="detector-confidence">Confidence</Field.Label>
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
						</Field.Field>
					{:else}
						<Field.Set>
							<Field.Legend>Confidence per class</Field.Legend>
							<Field.Group class="grid grid-cols-1 sm:grid-cols-2">
								{#each Object.keys(detector.yolo.confidence) as name (name)}
									<Field.Field>
										<Field.Label for={`confidence-${name}`}>{name}</Field.Label>
										<Input
											id={`confidence-${name}`}
											type="number"
											min="0"
											max="1"
											step="0.01"
											bind:value={detector.yolo.confidence[name]}
											disabled={pending}
										/>
									</Field.Field>
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
					</Field.Field>
				{:else}
					<p class="text-sm text-muted-foreground">
						Snapshot mode saves the latest frame without object detection.
					</p>
				{/if}
				<Field.Set>
					<Field.Legend>Telegram notifications</Field.Legend>
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
										>{testing === channel.label ? 'Sending…' : 'Test notification'}</Button
									>
								</div>
								{#if exporter}
									<Field.Label for={`alert-${index}`}>Alert every</Field.Label>
									<Input
										id={`alert-${index}`}
										type="number"
										min="1"
										step="1"
										bind:value={exporter.alert_every}
										placeholder="Default: 1"
										disabled={pending}
									/>
								{/if}
							</Field.Field>
						{/each}
						<Button
							href={setupMode ? '/notifications/add?setup=1' : '/notifications/add'}
							target="_blank"
							rel="noopener"
							variant="outline"
						>
							<Plus /> Add Telegram channel</Button
						>
					</Field.Group>
				</Field.Set>
			</Field.Group>
		{/if}
		{#if error}
			<Alert.Root variant="destructive">
				<Alert.Title>Could not update detector</Alert.Title>
				<Alert.Description>{error}</Alert.Description>
			</Alert.Root>
		{/if}
		<div class="flex flex-wrap gap-2">
			{#if originalLabel}
				<Button type="button" variant="destructive" onclick={remove} disabled={pending}
					>Delete</Button
				>
			{/if}
			<Button type="submit" disabled={pending || (advanced && editorHasErrors)}
				>{pending ? 'Working…' : setupMode ? 'Save setup' : 'Save'}</Button
			>
		</div>
	</form>
</section>

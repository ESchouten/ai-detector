<script lang="ts">
	import { errorMessage } from '$lib/remote-errors';
	import { onDestroy, onMount, tick, untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Badge } from '$lib/components/ui/badge';
	import { Separator } from '$lib/components/ui/separator';
	import { ArrowLeft, ArrowRight, Camera, HardDrive, Search, Settings2 } from '@lucide/svelte';
	import * as Card from '$lib/components/ui/card';
	import * as Field from '$lib/components/ui/field';
	import * as Alert from '$lib/components/ui/alert';
	import * as NativeSelect from '$lib/components/ui/native-select';
	import * as RadioGroup from '$lib/components/ui/radio-group';
	import DetectorRuntime from './detector-runtime.svelte';
	import CameraPicture from './camera-picture.svelte';
	import CameraSetupProgress from './camera-setup-progress.svelte';
	import CameraBatch from './camera-batch.svelte';
	import CameraSetupSteps from './camera-setup-steps.svelte';
	import type { BatchCamera, BatchConnection } from '$lib/camera-batch';
	import type { StreamMeta } from '$lib/schema';
	import { discoverCameras, getCameraConnection } from '$lib/remote/camera.remote';
	import { checkCameraRecording } from '$lib/camera-check';
	import { cameraDraftAddress, cameraEditConnection } from '$lib/cameras';
	import { getCameras, removeCamera, saveCamera } from '$lib/remote/stream.remote';
	import { getDetectorPresets } from '$lib/remote/detector.remote';
	import { cameraMonitoringChoice } from '$lib/detector-editor';
	import { startDetector } from '$lib/remote/runtime.remote';

	let { initial }: { initial?: StreamMeta & { id: string; monitored: boolean } } = $props();
	const { catalogue, warning: catalogueWarning } = await getDetectorPresets();
	const cameras = $derived(await getCameras());
	const monitoredCameras = $derived(cameras.filter((camera) => camera.monitored));
	const existingCamera = $derived(cameras.find((camera) => camera.id === initial?.id));
	let step = $state<1 | 2>(1);
	let label = $state(untrack(() => initial?.label ?? ''));
	let source = $state(untrack(() => initial?.source ?? ''));
	let monitoringSelection = $state(
		untrack(() =>
			initial ? 'keep' : catalogue.defaultPreset ? `preset:${catalogue.defaultPreset}` : ''
		)
	);
	const monitoring = $derived(cameraMonitoringChoice(monitoringSelection));
	const selectedPreset = $derived(
		monitoring?.mode === 'preset'
			? catalogue.presets.find((preset) => preset.id === monitoring.preset)
			: undefined
	);
	let copyFromCameraId = $state('');
	const copiedCamera = $derived(monitoredCameras.find((camera) => camera.id === copyFromCameraId));
	const editing = untrack(() => cameraEditConnection(initial?.source ?? ''));
	let address = $state(untrack(() => initial?.connection?.address ?? ''));
	let username = $state(editing.username);
	let password = $state('');
	let streamUri = $state(editing.streamUri);
	let profiles = $state<{ token: string; name: string }[]>([]);
	let profileToken = $state(untrack(() => initial?.connection?.profileToken ?? ''));
	let verifiedConnection = $state<StreamMeta['connection']>(untrack(() => initial?.connection));
	let manualAddress = $state(false);
	let advancedAddress = $state(false);
	let changingConnection = $state(untrack(() => !initial));
	let candidates = $state<Awaited<ReturnType<typeof discoverCameras>>['cameras']>([]);
	let discoveryMessage = $state('');
	let batchEnabled = $state(false);
	let batchConnecting = $state(false);
	let batchQueue = $state<BatchCamera[]>([]);
	let batchAddress = $state('');
	let preparedConnection = $state<BatchConnection>();
	const nextBatchCamera = $derived(
		batchQueue.find((camera) => camera.state === 'ready' && camera.address !== batchAddress)
	);
	let checking = $state(false);
	let finding = $state(false);
	let saving = $state(false);
	let error = $state('');
	let errorPanel = $state<HTMLDivElement>();
	let cameraForm = $state<HTMLFormElement>();
	$effect(() => {
		if (error) errorPanel?.focus();
	});
	let check = $state<Awaited<ReturnType<typeof checkCameraRecording>>>();
	let checkController: AbortController | undefined;
	onDestroy(() => checkController?.abort());
	let confirmed = $state(false);
	let saved = $state<{ id: string; monitored: boolean }>();
	let confirmingRemoval = $state(false);
	let restoreDraft = $state(false);
	const connectionChanged = $derived(changingConnection && !check);
	const canContinue = $derived(
		Boolean(label.trim()) && !connectionChanged && (!check || confirmed)
	);
	const canSave = $derived(
		canContinue &&
			monitoring &&
			(monitoring.mode !== 'preset' || selectedPreset) &&
			(monitoring.mode !== 'copy' || copiedCamera)
	);

	onMount(() => {
		if (initial) return;
		const draft = sessionStorage.getItem('camera-setup');
		if (draft) {
			try {
				const parsed = JSON.parse(draft);
				if (typeof parsed.label === 'string') label = parsed.label;
				if (typeof parsed.address === 'string') address = cameraDraftAddress(parsed.address) ?? '';
				const selection =
					typeof parsed.monitoringSelection === 'string'
						? parsed.monitoringSelection
						: typeof parsed.preset === 'string'
							? ['copy', 'view-only'].includes(parsed.preset)
								? parsed.preset
								: `preset:${parsed.preset}`
							: '';
				if (cameraMonitoringChoice(selection) && selection !== 'keep')
					monitoringSelection = selection;
				if (typeof parsed.copyFromCameraId === 'string') copyFromCameraId = parsed.copyFromCameraId;
			} catch {
				sessionStorage.removeItem('camera-setup');
			}
		}
		restoreDraft = true;
		void find();
	});
	$effect(() => {
		if (restoreDraft && !saved)
			sessionStorage.setItem(
				'camera-setup',
				JSON.stringify({
					label,
					address: cameraDraftAddress(address),
					monitoringSelection,
					copyFromCameraId: monitoring?.mode === 'copy' ? copyFromCameraId : undefined
				})
			);
	});

	function invalidateCheck() {
		check = undefined;
		confirmed = false;
		error = '';
	}
	function connectionChangedInput() {
		preparedConnection = undefined;
		profiles = [];
		profileToken = '';
		invalidateCheck();
	}
	function credentialsChangedInput() {
		preparedConnection = undefined;
		invalidateCheck();
	}
	async function chooseStep(next: 1 | 2) {
		if (next === 2 && !canContinue) return;
		step = next;
		await tick();
		cameraForm?.focus();
	}
	async function openBatchCamera(camera: BatchCamera) {
		if (!camera.connection || !camera.login) return;
		step = 1;
		saved = undefined;
		batchAddress = camera.address;
		label = camera.name;
		address = camera.address;
		username = camera.login.username;
		password = camera.login.password;
		source = '';
		streamUri = '';
		advancedAddress = false;
		manualAddress = false;
		profiles = camera.connection.profiles;
		profileToken =
			camera.profileToken ?? camera.connection.connection?.profileToken ?? profiles[0]?.token ?? '';
		preparedConnection = camera.profileToken ? undefined : camera.connection;
		verifiedConnection = camera.connection.connection;
		batchQueue = batchQueue.map((item) =>
			item.address === camera.address ? { ...item, state: 'ready' } : item
		);
		invalidateCheck();
		await tick();
		cameraForm?.focus();
	}
	function skipBatchCamera() {
		batchQueue = batchQueue.map((camera) =>
			camera.address === batchAddress
				? { ...camera, name: label, profileToken, login: { username, password }, state: 'skipped' }
				: camera
		);
		batchAddress = '';
		preparedConnection = undefined;
		label = '';
		address = '';
		source = '';
		invalidateCheck();
	}
	function leaveBatch() {
		batchEnabled = false;
		batchQueue = [];
		batchAddress = '';
		addAnother();
	}
	function chooseChannelAgain() {
		source = '';
		verifiedConnection = undefined;
		connectionChangedInput();
	}
	async function find() {
		finding = true;
		error = '';
		try {
			const result = await discoverCameras();
			candidates = result.cameras;
			discoveryMessage =
				result.message ??
				(candidates.length
					? 'Choose your camera below.'
					: 'No cameras found. Enter its address below, or check that the camera and this computer use the same network.');
		} catch (cause) {
			discoveryMessage = errorMessage(
				cause,
				'Camera search failed. Check the network and try again.'
			);
			error = discoveryMessage;
		} finally {
			finding = false;
		}
	}
	async function verify() {
		const controller = new AbortController();
		checkController = controller;
		checking = true;
		invalidateCheck();
		try {
			const connection =
				initial && !changingConnection
					? { source, profiles, connection: initial.connection }
					: (preparedConnection ??
						(await getCameraConnection({
							address,
							username,
							password,
							...(profileToken ? { profileToken } : {}),
							...(advancedAddress ? { streamUri } : {})
						})));
			controller.signal.throwIfAborted();
			profiles = connection.profiles;
			verifiedConnection = connection.connection;
			profileToken ||= profiles[0]?.token ?? '';
			check = await checkCameraRecording(
				connection.source,
				controller.signal,
				resolve('/camera-checks')
			);
			source = check.source;
		} catch (cause) {
			if (controller.signal.aborted) return;
			error = errorMessage(
				cause,
				'Could not connect to the camera. Check its address and password.'
			);
		} finally {
			checkController = undefined;
			checking = false;
		}
	}
	async function submit(event: SubmitEvent) {
		event.preventDefault();
		if (step === 1) {
			await chooseStep(2);
			return;
		}
		if (!canSave || !monitoring) return;
		saving = true;
		error = '';
		try {
			saved = await saveCamera({
				label,
				source,
				...(monitoring.mode === 'copy'
					? { mode: 'copy' as const, copyFromCameraId }
					: { ...monitoring, id: initial?.id }),
				checkId: check?.checkId,
				...(changingConnection ? { connection: verifiedConnection ?? null } : {})
			}).updates(getCameras());
			if (batchAddress) {
				const savedId = saved.id;
				batchQueue = batchQueue.map((camera) =>
					camera.address === batchAddress
						? { address: camera.address, name: label, state: 'saved', savedId }
						: camera
				);
			}
			sessionStorage.removeItem('camera-setup');
			if (saved.monitored && !initial) await startDetector('auto');
		} catch (cause) {
			error = saved
				? 'Your camera is saved. Monitoring could not be started. Use Start monitoring below to try again.'
				: errorMessage(cause, 'The camera could not be saved. Your choices are still here.');
		} finally {
			saving = false;
		}
	}
	async function remove() {
		if (!initial) return;
		saving = true;
		try {
			await removeCamera(initial.id).updates(getCameras());
			await goto(resolve('/streams'));
		} catch (cause) {
			error = errorMessage(cause, 'Could not remove this camera.');
		} finally {
			saving = false;
		}
	}
	function addAnother() {
		if (initial) {
			void goto(resolve('/streams/add'));
			return;
		}
		saved = undefined;
		step = 1;
		label = '';
		source = '';
		address = '';
		username = '';
		password = '';
		streamUri = '';
		monitoringSelection = catalogue.defaultPreset ? `preset:${catalogue.defaultPreset}` : '';
		copyFromCameraId = '';
		advancedAddress = false;
		manualAddress = false;
		verifiedConnection = undefined;
		profileToken = '';
		profiles = [];
		preparedConnection = undefined;
		candidates = [];
		discoveryMessage = '';
		invalidateCheck();
		void find();
	}
</script>

<section class="settings-page flex flex-col gap-7">
	<header class="flex flex-wrap items-start justify-between gap-4">
		<div class="flex flex-col gap-2">
			<h1 class="settings-heading">
				{saved ? `${label} is saved` : initial ? 'Camera settings' : 'Add your camera'}
			</h1>
			<p class="settings-description">
				{saved
					? 'Finish the checks below, or return later. Your camera is saved.'
					: 'Connect a camera, check the picture, and choose what to watch for.'}
			</p>
		</div>
		{#if !initial && !saved && !batchEnabled}
			<Button
				type="button"
				variant="outline"
				disabled={finding || checking || saving}
				onclick={() => {
					batchEnabled = true;
					batchAddress = '';
					step = 1;
					invalidateCheck();
				}}>Set up several cameras</Button
			>
		{/if}
	</header>

	<CameraSetupSteps
		current={saved ? 3 : step}
		{canContinue}
		disabled={checking || saving || (batchEnabled && !batchAddress)}
		onchoose={chooseStep}
	/>

	{#if batchEnabled}
		<CameraBatch
			{candidates}
			{finding}
			{discoveryMessage}
			onfind={find}
			bind:queue={batchQueue}
			bind:connecting={batchConnecting}
			activeAddress={batchAddress}
			activeSaved={Boolean(saved)}
			disabled={checking || saving}
			onchoose={openBatchCamera}
			onskip={skipBatchCamera}
			onclose={leaveBatch}
		/>
	{/if}

	{#if !batchEnabled || batchAddress || saved}
		<div class="settings-layout">
			<div class="flex min-w-0 flex-col gap-5">
				{#if saved}
					{#if error}
						<div tabindex="-1" bind:this={errorPanel}>
							<Alert.Root variant="destructive"
								><Alert.Title>Camera saved; monitoring needs attention</Alert.Title
								><Alert.Description>{error}</Alert.Description></Alert.Root
							>
						</div>
					{/if}
					{#if saved.monitored}<DetectorRuntime configured />{:else}
						<Alert.Root
							><Alert.Title>View only</Alert.Title><Alert.Description
								>This camera is available for live viewing. It will not record events or send
								alerts.</Alert.Description
							></Alert.Root
						>
					{/if}
					{#key saved.id}<CameraSetupProgress
							id={saved.id}
							checkId={check?.checkId}
							externalLinks={batchEnabled}
						/>{/key}
					<div class="flex flex-wrap gap-3">
						{#if batchEnabled}
							{#if nextBatchCamera}<Button
									type="button"
									disabled={saving || checking || batchConnecting}
									onclick={() => nextBatchCamera && openBatchCamera(nextBatchCamera)}
									>Set up next camera <ArrowRight data-icon="inline-end" /></Button
								>{/if}
						{:else}<Button type="button" onclick={addAnother} disabled={saving} variant="outline"
								>Add another camera</Button
							>{/if}
						<Button
							href={resolve('/streams')}
							target={batchEnabled ? '_blank' : undefined}
							rel="noopener"
							variant="outline">Open cameras</Button
						>
					</div>
					{#if batchEnabled}<p class="text-sm text-muted-foreground">
							You can continue with the next camera before finishing these checks. Saved cameras
							with incomplete setup remain available from Settings.
						</p>{/if}
				{:else}
					<form
						onsubmit={submit}
						class="flex flex-col gap-5"
						bind:this={cameraForm}
						tabindex="-1"
						aria-label={step === 1 ? 'Connect camera' : 'Choose monitoring'}
					>
						{#if step === 1}
							<Card.Root>
								<Card.Header class="flex flex-wrap items-start justify-between gap-4">
									<div class="flex flex-col gap-2">
										<Card.Title>Connect your camera</Card.Title><Card.Description
											>Keep the camera and this computer on the same network.</Card.Description
										>
									</div>
									{#if changingConnection && !batchAddress}<Button
											type="button"
											variant="outline"
											disabled={finding || checking || saving}
											onclick={find}
											><Search data-icon="inline-start" />{finding
												? 'Looking for cameras…'
												: 'Find cameras'}</Button
										>{/if}
								</Card.Header>
								<Card.Content class="flex flex-col gap-6">
									{#if initial && !changingConnection}
										<CameraPicture id={initial.id} {label} monitored={initial.monitored} />
										<p class="text-sm text-muted-foreground">
											Your saved connection is kept. You can change the name or monitoring settings
											without reconnecting.
										</p>
										<div class="flex flex-wrap gap-2">
											<Button
												type="button"
												variant="outline"
												disabled={checking || saving}
												onclick={verify}
												>{checking ? 'Checking picture…' : 'Confirm picture and recording'}</Button
											>
											<Button
												type="button"
												variant="outline"
												disabled={checking || saving}
												onclick={() => {
													changingConnection = true;
													if (!initial.connection) {
														manualAddress = true;
														advancedAddress = true;
													}
												}}>Change address or password</Button
											>
										</div>
									{:else}
										{#if !batchAddress}
											{#if discoveryMessage}<p class="text-sm text-muted-foreground" role="status">
													{discoveryMessage}
												</p>{/if}
											{#if candidates.length}
												<RadioGroup.Root
													value={address}
													aria-label="Discovered cameras"
													disabled={checking || saving}
													onValueChange={(value) => {
														address = value;
														manualAddress = false;
														advancedAddress = false;
														if (!label)
															label =
																candidates.find((camera) => camera.address === value)?.name ?? '';
														connectionChangedInput();
													}}
												>
													{#each candidates as camera, index (camera.address)}
														<Field.Label for={`camera-choice-${index}`} class="cursor-pointer">
															<Field.Field orientation="horizontal">
																<RadioGroup.Item
																	id={`camera-choice-${index}`}
																	value={camera.address}
																/>
																<Field.Content
																	><Field.Title>{camera.name}</Field.Title><Field.Description
																		class="break-all">{camera.address}</Field.Description
																	></Field.Content
																>
															</Field.Field>
														</Field.Label>
													{/each}
												</RadioGroup.Root>
											{/if}
											<Button
												type="button"
												variant="link"
												class="h-auto justify-start self-start p-0"
												disabled={checking || saving}
												onclick={() => (manualAddress = !manualAddress)}
												>{manualAddress ? 'Hide manual connection' : 'Camera not found'}</Button
											>
										{:else}
											<p class="flex flex-wrap items-center gap-2 text-sm">
												<Badge variant="secondary">Selected camera</Badge><span>{label}</span>
											</p>
										{/if}
										{#if cameraDraftAddress(address) && !manualAddress && !candidates.some((camera) => camera.address === address)}<p
												class="text-sm break-all text-muted-foreground"
											>
												Camera selected: {address}
											</p>{/if}
										{#if initial?.connection?.profileToken && profileToken}
											<div class="flex flex-col gap-2">
												<Button
													type="button"
													variant="outline"
													class="self-start"
													disabled={checking || saving}
													onclick={chooseChannelAgain}>Choose camera channel again</Button
												>
												<p class="text-sm text-muted-foreground">
													Use this if the recorder’s channels have changed. Enter its login, then
													check the picture to choose the right camera.
												</p>
											</div>
										{/if}
										<Field.Group>
											{#if manualAddress}<Field.Field
													><Field.Label for="camera-address">Camera address</Field.Label><Input
														id="camera-address"
														bind:value={address}
														oninput={connectionChangedInput}
														disabled={checking || saving}
														placeholder="e.g. 192.168.1.50"
														autocomplete="off"
													/><Field.Description
														>Enter the camera’s network address. Allow local network access if this
														computer asks.</Field.Description
													></Field.Field
												>{/if}
											<Field.Group class="grid gap-4 sm:grid-cols-2">
												<Field.Field
													><Field.Label for="camera-username">Camera username</Field.Label><Input
														id="camera-username"
														bind:value={username}
														oninput={credentialsChangedInput}
														disabled={checking || saving}
														autocomplete="off"
													/></Field.Field
												>
												<Field.Field
													><Field.Label for="camera-password">Camera password</Field.Label><Input
														id="camera-password"
														type="password"
														bind:value={password}
														oninput={credentialsChangedInput}
														disabled={checking || saving}
														autocomplete="off"
													/></Field.Field
												>
											</Field.Group>
											<Field.Description
												>Use your camera’s own login, which may differ from its phone app.</Field.Description
											>
										</Field.Group>
										{#if manualAddress}<details
												open={advancedAddress}
												inert={checking || saving}
												ontoggle={(event) => {
													if (advancedAddress === event.currentTarget.open) return;
													advancedAddress = event.currentTarget.open;
													connectionChangedInput();
												}}
											>
												<summary class="cursor-pointer text-sm"
													>Use a stream address instead</summary
												>
												<Field.Field class="mt-4"
													><Field.Label for="camera-stream">RTSP or HTTP stream address</Field.Label
													><Input
														id="camera-stream"
														type="password"
														bind:value={streamUri}
														oninput={connectionChangedInput}
														disabled={checking || saving}
														placeholder="rtsp://192.168.1.50/stream"
														autocomplete="off"
													/><Field.Description
														>Ask your camera installer for its stream address. A camera’s web page
														is not a video stream.</Field.Description
													></Field.Field
												>
											</details>{/if}
										{#if profiles.length > 1}<Field.Field
												><Field.Label for="camera-profile">Camera channel or stream</Field.Label
												><NativeSelect.Root
													id="camera-profile"
													bind:value={profileToken}
													onchange={credentialsChangedInput}
													disabled={checking || saving}
													>{#each profiles as profile (profile.token)}<NativeSelect.Option
															value={profile.token}>{profile.name}</NativeSelect.Option
														>{/each}</NativeSelect.Root
												><Field.Description
													>Choose the correct channel, then check its picture again.</Field.Description
												></Field.Field
											>{/if}
									{/if}
									{#if check}
										<Separator />
										<div class="flex flex-col gap-4">
											<div class="flex flex-wrap items-center justify-between gap-3">
												<h2 class="font-medium">Confirm the picture and recording</h2>
												<Button
													type="button"
													variant="outline"
													disabled={checking || saving}
													onclick={verify}>{checking ? 'Checking picture…' : 'Check again'}</Button
												>
											</div>
											<img
												src={check.previewUrl}
												alt="Camera connection test"
												class="aspect-video w-full rounded-md bg-muted object-contain"
											/>
											{#if check.recordingUrl}<video
													controls
													preload="metadata"
													class="w-full rounded-md"
													><source src={check.recordingUrl} type="video/mp4" /><track
														kind="captions"
													/></video
												>{/if}
											<p class="text-sm text-muted-foreground">
												Play this short test to check the right camera is connected. It is a setup
												test, not a detected event.
											</p>
											<Field.Field orientation="horizontal"
												><Checkbox
													id="camera-confirm"
													bind:checked={confirmed}
													disabled={saving || checking}
												/><Field.Label for="camera-confirm"
													>This is the right camera and the test recording plays</Field.Label
												></Field.Field
											>
										</div>
									{/if}
									{#if check || initial}<Field.Field
											><Field.Label for="camera-name">Camera name</Field.Label><Input
												id="camera-name"
												bind:value={label}
												disabled={saving}
												required
												placeholder="e.g. Front entrance"
											/><Field.Description
												>Choose a name you will recognise in Cameras and Recordings.</Field.Description
											></Field.Field
										>{/if}
								</Card.Content>
								<Card.Footer class="flex flex-wrap gap-3">
									{#if !check && changingConnection}<Button
											type="button"
											disabled={checking || saving || (!address.trim() && !streamUri.trim())}
											onclick={verify}
											>{checking
												? 'Checking picture and recording…'
												: 'Check picture and recording'}<ArrowRight
												data-icon="inline-end"
											/></Button
										>
									{:else}<Button type="submit" disabled={checking || saving || !canContinue}
											>Continue to monitoring<ArrowRight data-icon="inline-end" /></Button
										>{/if}
									<Button href={resolve('/streams')} variant="outline">Cancel</Button>
								</Card.Footer>
							</Card.Root>
						{:else}
							<Card.Root>
								<Card.Header
									><Card.Title>Choose what to watch for</Card.Title><Card.Description
										>These settings apply to {label}. You can change them later.</Card.Description
									></Card.Header
								>
								<Card.Content class="flex flex-col gap-6">
									<div class="flex flex-wrap items-center justify-between gap-3">
										<div class="flex items-center gap-3">
											<Camera class="size-5 text-muted-foreground" />
											<div class="flex flex-col gap-1">
												<p class="font-medium">{label}</p>
												<p class="text-sm text-muted-foreground">
													{check && confirmed
														? 'Picture and recording confirmed'
														: 'Using your saved connection'}
												</p>
											</div>
										</div>
										<Button
											type="button"
											variant="outline"
											disabled={saving}
											onclick={() => chooseStep(1)}>Edit camera</Button
										>
									</div>
									<Separator />
									{#if catalogueWarning}<Alert.Root variant="destructive"
											><Alert.Title>Monitoring presets are unavailable</Alert.Title
											><Alert.Description
												>{catalogueWarning} You can still keep existing settings, copy another camera’s
												settings, or choose viewing only.</Alert.Description
											></Alert.Root
										>{/if}
									<Field.Group>
										<Field.Field
											><Field.Label for="camera-purpose">Watch for</Field.Label><NativeSelect.Root
												id="camera-purpose"
												bind:value={monitoringSelection}
												disabled={saving}
												required
											>
												<NativeSelect.Option value="">Choose what to watch for</NativeSelect.Option>
												{#if initial}<NativeSelect.Option value="keep"
														>Keep current monitoring settings</NativeSelect.Option
													>{/if}
												{#if !initial && (monitoredCameras.length || monitoring?.mode === 'copy')}<NativeSelect.Option
														value="copy"
														>Use the same settings as an existing camera</NativeSelect.Option
													>{/if}
												{#each catalogue.presets as preset (preset.id)}<NativeSelect.Option
														value={`preset:${preset.id}`}>{preset.name}</NativeSelect.Option
													>{/each}
												{#if monitoring?.mode === 'preset' && !selectedPreset}<NativeSelect.Option
														value={monitoringSelection}
														disabled
														>Previous choice unavailable — choose another</NativeSelect.Option
													>{/if}
												<NativeSelect.Option value="view-only"
													>View only — do not monitor events</NativeSelect.Option
												>
											</NativeSelect.Root><Field.Description
												>{selectedPreset
													? selectedPreset.description
													: monitoring?.mode === 'view-only'
														? 'The camera will appear in Cameras, but will not record events or send alerts.'
														: monitoring?.mode === 'copy'
															? 'Copy watched events, recording options and alert recipients. Each camera can be changed separately afterward.'
															: monitoring?.mode === 'keep'
																? 'Your current rules, custom settings and alert recipients are preserved.'
																: 'Choose a monitoring option, or use this camera for viewing only.'}</Field.Description
											></Field.Field
										>
										{#if selectedPreset?.guidance}<Field.Description
												>{selectedPreset.guidance}</Field.Description
											>{/if}
										{#if monitoring?.mode === 'keep' && existingCamera}<div
												class="flex flex-col gap-2 text-sm"
											>
												<p>
													<span class="font-medium">Current rules:</span>
													{existingCamera.rules.length
														? existingCamera.rules.map((rule) => rule.label).join(', ')
														: 'View only'}
												</p>
												<p>
													<span class="font-medium">Alerts:</span>
													{existingCamera.alerts.length
														? existingCamera.alerts.join(', ')
														: 'None connected'}
												</p>
											</div>{/if}
										{#if initial && monitoring?.mode === 'preset'}<Field.Description
												>This replaces the camera’s current monitoring rules. Its recording
												destinations and alert recipients are kept.</Field.Description
											>{/if}
										{#if monitoring?.mode === 'copy'}<Field.Field
												><Field.Label for="copy-camera"
													>Use the same monitoring settings as</Field.Label
												><NativeSelect.Root
													id="copy-camera"
													bind:value={copyFromCameraId}
													disabled={saving}
													required
													><NativeSelect.Option value="">Choose a camera</NativeSelect.Option
													>{#each monitoredCameras as camera (camera.id)}<NativeSelect.Option
															value={camera.id}>{camera.label}</NativeSelect.Option
														>{/each}</NativeSelect.Root
												><Field.Description
													>{#if copiedCamera}Watched events: {copiedCamera.rules
															.map((rule) => rule.label)
															.join(', ')}. Alerts: {copiedCamera.alerts.length
															? copiedCamera.alerts.join(', ')
															: 'None connected'}.{:else}Choose a monitored camera. View-only
														cameras have no monitoring settings to copy.{/if}</Field.Description
												></Field.Field
											>{/if}
									</Field.Group>
								</Card.Content>
								<Card.Footer class="flex flex-wrap gap-3"
									><Button type="submit" disabled={saving || checking || !canSave}
										>{saving
											? 'Saving camera…'
											: initial
												? 'Save changes'
												: monitoring?.mode === 'view-only'
													? 'Save for viewing'
													: 'Save and start monitoring'}<ArrowRight
											data-icon="inline-end"
										/></Button
									><Button
										type="button"
										variant="outline"
										disabled={saving}
										onclick={() => chooseStep(1)}><ArrowLeft data-icon="inline-start" />Back</Button
									></Card.Footer
								>
							</Card.Root>
						{/if}
						{#if error}<div tabindex="-1" bind:this={errorPanel}>
								<Alert.Root variant="destructive"
									><Alert.Title>Camera needs attention</Alert.Title><Alert.Description
										>{error}</Alert.Description
									></Alert.Root
								>
							</div>{/if}
						{#if initial}<details>
								<summary class="cursor-pointer text-sm text-muted-foreground"
									>Remove this camera</summary
								>
								<p class="my-3 text-sm">
									Monitoring and alerts for {label} will stop. Existing recordings stay on this computer.
								</p>
								<Field.Field orientation="horizontal"
									><Checkbox
										id="confirm-remove-camera"
										bind:checked={confirmingRemoval}
									/><Field.Label for="confirm-remove-camera"
										>Stop monitoring and remove this camera</Field.Label
									></Field.Field
								><Button
									class="mt-3"
									type="button"
									variant="destructive"
									disabled={!confirmingRemoval || saving}
									onclick={remove}>Remove camera</Button
								>
							</details>{/if}
					</form>
				{/if}
			</div>
			<aside class="settings-aside flex flex-col gap-6">
				{#if saved}<section class="flex flex-col gap-3">
						<Settings2 class="size-6 text-muted-foreground" />
						<h2 class="font-semibold">Finish at your own pace</h2>
						<p class="text-sm text-muted-foreground">
							Your camera is saved. Monitoring, recording storage and alerts have their own checks.
							You can return to unfinished setup from Settings.
						</p>
					</section>
				{:else if step === 1}<section class="flex flex-col gap-3">
						<Camera class="size-6 text-muted-foreground" />
						<h2 class="font-semibold">Before you start</h2>
						<ol class="flex list-decimal flex-col gap-3 pl-5 text-sm text-muted-foreground">
							<li>Keep the camera powered on.</li>
							<li>Use the same local network.</li>
							<li>Have the camera login ready.</li>
						</ol>
						{#if manualAddress}<p class="text-sm text-muted-foreground">
								If discovery does not find your camera, check that camera discovery (ONVIF) is
								enabled in its settings.
							</p>{/if}
					</section>
				{:else}<section class="flex flex-col gap-3">
						<Settings2 class="size-6 text-muted-foreground" />
						<h2 class="font-semibold">Choose the right monitoring</h2>
						<p class="text-sm text-muted-foreground">
							Choose settings for what you want to watch. You can copy another camera’s settings
							when adding a camera, or choose viewing only.
						</p>
						{#if initial}<p class="text-sm text-muted-foreground">
								Keep current settings to preserve custom or multiple rules. Manage them individually
								in Monitoring rules in Settings.
							</p>{/if}
					</section>{/if}
				<Separator />
				<section class="flex flex-col gap-3">
					<HardDrive class="size-6 text-muted-foreground" />
					<h2 class="font-semibold">Recordings and alerts</h2>
					<p class="text-sm text-muted-foreground">
						When recording is enabled, clips stay on this computer. Phone alerts are optional.
					</p>
				</section>
			</aside>
		</div>
	{/if}
</section>

<script lang="ts">
	import { errorMessage } from '$lib/remote-errors';
	import { onDestroy, onMount, untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import * as Card from '$lib/components/ui/card';
	import * as Field from '$lib/components/ui/field';
	import * as Alert from '$lib/components/ui/alert';
	import * as NativeSelect from '$lib/components/ui/native-select';
	import DetectorRuntime from './detector-runtime.svelte';
	import CameraPicture from './camera-picture.svelte';
	import CameraSetupProgress from './camera-setup-progress.svelte';
	import type { StreamMeta } from '$lib/schema';
	import { discoverCameras, getCameraConnection } from '$lib/remote/camera.remote';
	import { checkCameraRecording } from '$lib/camera-check';
	import { cameraDraftAddress, cameraEditConnection } from '$lib/cameras';
	import { getCameras, removeCamera, saveCamera } from '$lib/remote/stream.remote';
	import { startDetector } from '$lib/remote/runtime.remote';

	let { initial }: { initial?: StreamMeta & { id: string; monitored: boolean } } = $props();
	const newCameraPresets = ['calving', 'mounts', 'general', 'view-only', 'copy'] as const;
	type Preset = (typeof newCameraPresets)[number] | 'keep';
	const cameras = $derived(await getCameras());
	const monitoredCameras = $derived(cameras.filter((camera) => camera.monitored));
	let label = $state(untrack(() => initial?.label ?? ''));
	let source = $state(untrack(() => initial?.source ?? ''));
	let preset = $state<Preset>(untrack(() => (initial ? 'keep' : 'calving')));
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
	let checking = $state(false);
	let finding = $state(false);
	let saving = $state(false);
	let error = $state('');
	let errorPanel = $state<HTMLDivElement>();
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
	const canSave = $derived(
		label.trim() &&
			!connectionChanged &&
			(!check || confirmed) &&
			(preset !== 'copy' || copiedCamera)
	);

	onMount(() => {
		if (initial) return;
		const draft = sessionStorage.getItem('camera-setup');
		if (draft) {
			try {
				const parsed = JSON.parse(draft);
				if (typeof parsed.label === 'string') label = parsed.label;
				if (typeof parsed.address === 'string') address = cameraDraftAddress(parsed.address) ?? '';
				if (newCameraPresets.includes(parsed.preset)) preset = parsed.preset;
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
					preset,
					copyFromCameraId: preset === 'copy' ? copyFromCameraId : undefined
				})
			);
	});

	function invalidateCheck() {
		check = undefined;
		confirmed = false;
		error = '';
	}
	function connectionChangedInput() {
		profiles = [];
		profileToken = '';
		invalidateCheck();
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
			error = errorMessage(cause, 'Camera search failed. You can enter the camera address below.');
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
					: await getCameraConnection({
							address,
							username,
							password,
							...(profileToken ? { profileToken } : {}),
							...(advancedAddress ? { streamUri } : {})
						});
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
		if (!canSave) return;
		saving = true;
		error = '';
		try {
			saved = await saveCamera({
				label,
				source,
				...(preset === 'copy' ? { preset, copyFromCameraId } : { preset, id: initial?.id }),
				checkId: check?.checkId,
				...(changingConnection ? { connection: verifiedConnection ?? null } : {})
			}).updates(getCameras());
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
		label = '';
		source = '';
		address = '';
		username = '';
		password = '';
		streamUri = '';
		preset = 'calving';
		copyFromCameraId = '';
		advancedAddress = false;
		manualAddress = false;
		verifiedConnection = undefined;
		profileToken = '';
		profiles = [];
		candidates = [];
		discoveryMessage = '';
		invalidateCheck();
		void find();
	}
</script>

<section class="flex w-full max-w-3xl flex-col gap-6 pb-8">
	<header class="flex flex-col gap-2">
		<h1 class="text-2xl font-semibold tracking-tight">
			{saved ? `${label} is saved` : initial ? 'Camera settings' : 'Add your camera'}
		</h1>
		<p class="text-muted-foreground">
			{saved
				? 'Check monitoring below. You can add alerts whenever you are ready.'
				: 'Choose a camera, confirm its picture, then choose what to watch for.'}
		</p>
	</header>
	{#if saved}
		{#if error}<div tabindex="-1" bind:this={errorPanel}>
				<Alert.Root variant="destructive"
					><Alert.Title>Monitoring has not started</Alert.Title><Alert.Description
						>{error}</Alert.Description
					></Alert.Root
				>
			</div>{/if}
		{#if saved.monitored}<DetectorRuntime configured />{:else}<Alert.Root
				><Alert.Title>View only</Alert.Title><Alert.Description
					>This camera is saved for live viewing. It is not recording events or sending alerts.</Alert.Description
				></Alert.Root
			>{/if}
		<CameraSetupProgress id={saved.id} checkId={check?.checkId} />
		<div class="flex flex-wrap gap-3">
			<Button href={resolve('/streams')}>Open cameras</Button>
			{#if saved.monitored}<Button
					href={resolve(`/notifications/add?camera=${saved.id}`)}
					variant="outline">Connect alerts</Button
				>{/if}
			<Button type="button" onclick={addAnother} variant="outline">Add another camera</Button>
		</div>
	{:else}
		<form class="flex flex-col gap-6" onsubmit={submit}>
			<Card.Root>
				<Card.Header
					><Card.Title>1. Connect your camera</Card.Title><Card.Description
						>Keep the camera and this computer on the same network.</Card.Description
					></Card.Header
				>
				<Card.Content class="flex flex-col gap-5">
					{#if initial && !changingConnection}
						<CameraPicture id={initial.id} {label} />
						<Button type="button" variant="outline" disabled={checking || saving} onclick={verify}
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
					{:else}
						<Button
							type="button"
							variant="outline"
							disabled={finding || checking || saving}
							onclick={find}>{finding ? 'Looking for cameras…' : 'Find cameras'}</Button
						>
						{#if discoveryMessage}<p class="text-sm text-muted-foreground" role="status">
								{discoveryMessage}
							</p>{/if}
						{#each candidates as camera (camera.address)}
							<Button
								type="button"
								variant={address === camera.address ? 'secondary' : 'outline'}
								class="h-auto items-start p-4 text-left whitespace-normal"
								disabled={checking || saving}
								onclick={() => {
									address = camera.address;
									manualAddress = false;
									advancedAddress = false;
									if (!label) label = camera.name;
									connectionChangedInput();
								}}
								><span class="flex flex-col gap-1"
									><span class="font-medium">{camera.name}</span><span
										class="text-xs text-muted-foreground"
										>{address === camera.address ? 'Selected camera · ' : ''}{camera.address}</span
									></span
								></Button
							>
						{/each}
						{#if cameraDraftAddress(address) && !manualAddress}<p
								class="text-sm text-muted-foreground"
							>
								Camera selected: {address}
							</p>{/if}
						{#if initial?.connection?.profileToken && profileToken}
							<div class="flex flex-col gap-2">
								<Button
									type="button"
									variant="outline"
									disabled={checking || saving}
									onclick={chooseChannelAgain}>Choose camera channel again</Button
								>
								<p class="text-sm text-muted-foreground">
									Use this if the recorder’s channels have changed. Enter its login, then check the
									picture to load the available channels and confirm the right camera.
								</p>
							</div>
						{/if}
						<Button
							type="button"
							variant="outline"
							disabled={checking || saving}
							onclick={() => (manualAddress = !manualAddress)}
							>{manualAddress ? 'Hide manual connection' : 'Camera not found'}</Button
						>
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
										>Camera not found? Enter its network address. Check that camera discovery
										(ONVIF) is enabled in the camera’s settings. Allow local network access if this
										computer asks.</Field.Description
									></Field.Field
								>{/if}
							<Field.Field
								><Field.Label for="camera-username">Camera username</Field.Label><Input
									id="camera-username"
									bind:value={username}
									oninput={invalidateCheck}
									disabled={checking || saving}
									autocomplete="off"
								/><Field.Description
									>Use the login for your camera, which may differ from its phone app.</Field.Description
								></Field.Field
							>
							<Field.Field
								><Field.Label for="camera-password">Camera password</Field.Label><Input
									id="camera-password"
									type="password"
									bind:value={password}
									oninput={invalidateCheck}
									disabled={checking || saving}
									autocomplete="off"
								/></Field.Field
							>
						</Field.Group>
						{#if manualAddress}<details
								bind:open={advancedAddress}
								inert={checking || saving}
								ontoggle={(event) => {
									advancedAddress = event.currentTarget.open;
									connectionChangedInput();
								}}
							>
								<summary class="cursor-pointer text-sm"
									>Camera not found? Use a stream address</summary
								><Field.Field class="mt-4"
									><Field.Label for="camera-stream">RTSP or HTTP stream address</Field.Label><Input
										id="camera-stream"
										type="password"
										bind:value={streamUri}
										oninput={connectionChangedInput}
										disabled={checking || saving}
										placeholder="rtsp://192.168.1.50/stream"
										autocomplete="off"
									/><Field.Description
										>Ask your camera installer for its stream address. A camera’s web page is not a
										video stream.</Field.Description
									></Field.Field
								>
							</details>{/if}
						<Button
							type="button"
							disabled={checking || saving || (!address.trim() && !streamUri.trim())}
							onclick={verify}
							>{checking
								? 'Connecting and testing a short recording…'
								: 'Check picture and recording'}</Button
						>
						{#if profiles.length > 1}<Field.Field
								><Field.Label for="camera-profile">Camera channel or stream</Field.Label
								><NativeSelect.Root
									id="camera-profile"
									bind:value={profileToken}
									onchange={invalidateCheck}
									disabled={checking || saving}
									>{#each profiles as profile (profile.token)}<NativeSelect.Option
											value={profile.token}>{profile.name}</NativeSelect.Option
										>{/each}</NativeSelect.Root
								><Field.Description
									>For a recorder with several cameras, choose the correct channel and check its
									picture again.</Field.Description
								></Field.Field
							>{/if}
					{/if}
					{#if check}
						<img
							src={check.previewUrl}
							alt="Camera connection test"
							class="aspect-video w-full rounded-md bg-muted object-contain"
						/>
						{#if check.recordingUrl}<video controls preload="metadata" class="w-full rounded-md"
								><source src={check.recordingUrl} type="video/mp4" /><track
									kind="captions"
								/></video
							>{/if}
						<p class="text-sm text-muted-foreground">
							This is a setup test recording, not a detected event. Check that it shows the correct
							camera and plays correctly.
						</p>
						<Field.Field orientation="horizontal"
							><Checkbox
								id="camera-confirm"
								bind:checked={confirmed}
								disabled={saving}
							/><Field.Label for="camera-confirm"
								>This is the right camera and the test recording plays</Field.Label
							></Field.Field
						>
					{/if}
					<Field.Field
						><Field.Label for="camera-name">Camera name</Field.Label><Input
							id="camera-name"
							bind:value={label}
							disabled={saving}
							required
							placeholder="e.g. Calving pen"
						/></Field.Field
					>
				</Card.Content>
			</Card.Root>
			<Card.Root>
				<Card.Header
					><Card.Title>2. What should we watch for?</Card.Title><Card.Description
						>Recordings stay on this computer. Alerts are optional.</Card.Description
					></Card.Header
				>
				<Card.Content
					><Field.Group
						><Field.Field
							><Field.Label for="camera-purpose">Watch for</Field.Label><NativeSelect.Root
								id="camera-purpose"
								bind:value={preset}
								disabled={saving}
							>
								{#if initial}<NativeSelect.Option value="keep"
										>Keep current monitoring settings</NativeSelect.Option
									>{/if}
								{#if !initial && (monitoredCameras.length || preset === 'copy')}
									<NativeSelect.Option value="copy"
										>Use the same settings as an existing camera</NativeSelect.Option
									>
								{/if}
								<NativeSelect.Option value="calving">Calving signs</NativeSelect.Option
								><NativeSelect.Option value="mounts">Cow mounting behaviour</NativeSelect.Option
								><NativeSelect.Option value="general"
									>People, animals and vehicles</NativeSelect.Option
								><NativeSelect.Option value="view-only"
									>View only — do not monitor events</NativeSelect.Option
								>
							</NativeSelect.Root></Field.Field
						><Field.Description
							>{preset === 'calving'
								? 'Keep the cow’s rear and the floor behind her clearly visible. Detection can miss events; keep your usual animal checks.'
								: preset === 'mounts'
									? 'Use a clear side view with the animals’ full bodies visible.'
									: preset === 'general'
										? 'Records recognised people, animals and vehicles. Fine-tune watched classes in Advanced settings.'
										: preset === 'view-only'
											? 'The camera will appear in Cameras, but no events or alerts will be generated.'
											: preset === 'copy'
												? 'Copy watched events, recording options and alert recipients. Each camera can be changed separately afterward.'
												: 'Existing watched events and alert recipients are preserved.'}</Field.Description
						>
						{#if preset === 'copy'}
							<Field.Field>
								<Field.Label for="copy-camera">Use the same monitoring settings as</Field.Label>
								<NativeSelect.Root
									id="copy-camera"
									bind:value={copyFromCameraId}
									disabled={saving}
									required
								>
									<NativeSelect.Option value="">Choose a camera</NativeSelect.Option>
									{#each monitoredCameras as camera (camera.id)}
										<NativeSelect.Option value={camera.id}>{camera.label}</NativeSelect.Option>
									{/each}
								</NativeSelect.Root>
								<Field.Description>
									{#if copiedCamera}
										Watched events: {copiedCamera.rules.map((rule) => rule.label).join(', ')}.
										Alerts: {copiedCamera.alerts.length
											? copiedCamera.alerts.join(', ')
											: 'None connected'}.
									{:else}
										Choose a monitored camera above. View-only cameras have no monitoring settings
										to copy.
									{/if}
								</Field.Description>
							</Field.Field>
						{/if}
					</Field.Group></Card.Content
				>
			</Card.Root>
			{#if error}<div tabindex="-1" bind:this={errorPanel}>
					<Alert.Root variant="destructive"
						><Alert.Title>Camera needs attention</Alert.Title><Alert.Description
							>{error}</Alert.Description
						></Alert.Root
					>
				</div>{/if}
			<div class="flex flex-wrap gap-3">
				<Button type="submit" disabled={saving || checking || !canSave}
					>{saving
						? 'Saving camera…'
						: initial
							? 'Save changes'
							: preset === 'view-only'
								? 'Save for viewing'
								: 'Save and start monitoring'}</Button
				><Button href={resolve('/streams')} variant="outline">Cancel</Button>
			</div>
			{#if initial}
				<details>
					<summary class="cursor-pointer text-sm text-muted-foreground">Remove this camera</summary>
					<p class="my-3 text-sm">
						Monitoring and alerts for {label} will stop. Existing recordings stay on this computer.
					</p>
					<Field.Field orientation="horizontal"
						><Checkbox id="confirm-remove-camera" bind:checked={confirmingRemoval} /><Field.Label
							for="confirm-remove-camera">Stop monitoring and remove this camera</Field.Label
						></Field.Field
					><Button
						class="mt-3"
						type="button"
						variant="destructive"
						disabled={!confirmingRemoval || saving}
						onclick={remove}>Remove camera</Button
					>
				</details>
			{/if}
		</form>
	{/if}
</section>

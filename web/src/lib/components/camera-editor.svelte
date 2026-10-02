<script lang="ts">
	import { errorMessage } from '$lib/remote-errors';
	import { onDestroy, onMount, untrack } from 'svelte';
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Badge } from '$lib/components/ui/badge';
	import { ArrowRight, Eye, EyeOff } from '@lucide/svelte';
	import * as Field from '$lib/components/ui/field';
	import * as InputGroup from '$lib/components/ui/input-group';
	import * as Alert from '$lib/components/ui/alert';
	import * as NativeSelect from '$lib/components/ui/native-select';
	import CameraDiscovery from './camera-discovery.svelte';
	import CameraPicture from './camera-picture.svelte';
	import CardOverlay from './card-overlay.svelte';
	import CameraBatch from './camera-batch.svelte';
	import type { StreamMeta } from '$lib/schema';
	import { discoverCameras, getCameraConnection } from '$lib/remote/camera.remote';
	import { checkCameraRecording } from '$lib/camera-check';
	import { cameraDraftAddress, cameraEditConnection } from '$lib/cameras';
	import { getCameras, removeCamera, saveCamera } from '$lib/remote/stream.remote';
	import { getDetectors } from '$lib/remote/detector.remote';
	import { uniqueLabel } from '$lib/configuration';

	let {
		initial,
		onDone,
		onCancel
	}: {
		initial?: StreamMeta & { id: string; monitored: boolean };
		onDone: () => Promise<void>;
		onCancel?: () => Promise<void>;
	} = $props();
	const cameras = await getCameras();
	const defaultLabel = uniqueLabel('Camera', new Set(cameras.map((camera) => camera.label)));
	let label = $state(untrack(() => initial?.label ?? defaultLabel));
	let source = $state(untrack(() => initial?.source ?? ''));
	const editing = untrack(() => cameraEditConnection(initial?.source ?? ''));
	let address = $state(untrack(() => initial?.connection?.address ?? ''));
	let username = $state(untrack(() => (initial ? editing.username : 'admin')));
	let password = $state('');
	let streamUri = $state(untrack(() => initial?.source ?? ''));
	let showStreamUri = $state(false);
	let profiles = $state<{ token: string; name: string }[]>([]);
	let profileToken = $state(untrack(() => initial?.connection?.profileToken ?? ''));
	let verifiedConnection = $state<StreamMeta['connection']>(untrack(() => initial?.connection));
	let manualAddress = $state(false);
	let changingConnection = $state(untrack(() => !initial));
	let candidates = $state<Awaited<ReturnType<typeof discoverCameras>>['cameras']>([]);
	let discoveryMessage = $state('');
	let batchEnabled = $state(false);
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
	let confirmingRemoval = $state(false);
	let restoreDraft = $state(false);
	const connectionChanged = $derived(changingConnection && !check);
	const canSave = $derived(Boolean(label.trim()) && !connectionChanged);

	onMount(() => {
		if (initial) {
			if (!initial.setup?.pictureVerifiedAt) void connect();
			return;
		}
		const draft = sessionStorage.getItem('camera-setup');
		if (draft) {
			try {
				const parsed = JSON.parse(draft);
				if (typeof parsed.label === 'string' && parsed.label.trim()) label = parsed.label;
				if (typeof parsed.address === 'string') address = cameraDraftAddress(parsed.address) ?? '';
			} catch {
				sessionStorage.removeItem('camera-setup');
			}
		}
		restoreDraft = true;
		void find();
	});
	$effect(() => {
		if (restoreDraft)
			sessionStorage.setItem(
				'camera-setup',
				JSON.stringify({
					label,
					address: cameraDraftAddress(address)
				})
			);
	});

	function invalidateCheck() {
		check = undefined;
		error = '';
	}
	function connectionChangedInput() {
		profiles = [];
		profileToken = '';
		invalidateCheck();
	}
	function credentialsChangedInput() {
		invalidateCheck();
	}
	function chooseChannelAgain() {
		source = '';
		verifiedConnection = undefined;
		connectionChangedInput();
	}
	function selectCamera(value: string) {
		const previousName = candidates.find((camera) => camera.address === address)?.name;
		address = value;
		manualAddress = false;
		if (!label || label === defaultLabel || label === previousName)
			label = candidates.find((camera) => camera.address === value)?.name ?? '';
		connectionChangedInput();
	}
	async function find() {
		finding = true;
		error = '';
		try {
			const result = await discoverCameras();
			candidates = result.cameras;
			if (!address && !streamUri.trim()) {
				if (!candidates.length) manualAddress = true;
				else if (candidates.length === 1 && !manualAddress) {
					address = candidates[0].address;
					if (label === defaultLabel) label = candidates[0].name;
				}
			}
			discoveryMessage =
				result.message ??
				(candidates.length
					? 'Choose your camera below.'
					: 'No cameras found. Enter its stream URL manually, or check that the camera and this computer use the same network.');
		} catch (cause) {
			if (!address) manualAddress = true;
			discoveryMessage = errorMessage(
				cause,
				'Camera search failed. Check the network and try again.'
			);
			error = discoveryMessage;
		} finally {
			finding = false;
		}
	}
	async function connect() {
		const controller = new AbortController();
		checkController = controller;
		checking = true;
		invalidateCheck();
		try {
			const connection =
				initial && !changingConnection
					? { source, profiles, connection: initial.connection }
					: await getCameraConnection(
							manualAddress
								? { streamUri }
								: { address, username, password, ...(profileToken ? { profileToken } : {}) }
						);
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
			error = errorMessage(cause, 'Could not connect to the camera. Check its connection details.');
		} finally {
			checkController = undefined;
			checking = false;
		}
	}
	async function submit(event: SubmitEvent) {
		event.preventDefault();
		if (connectionChanged) {
			await connect();
			return;
		}
		if (!canSave) return;
		saving = true;
		error = '';
		try {
			await saveCamera({
				label,
				source,
				id: initial?.id,
				mode: initial ? 'keep' : 'view-only',
				checkId: check?.checkId,
				...(changingConnection ? { connection: verifiedConnection ?? null } : {})
			}).updates(getCameras(), getDetectors());
			restoreDraft = false;
			sessionStorage.removeItem('camera-setup');
			await onDone();
		} catch (cause) {
			error = errorMessage(cause, 'The camera could not be saved. Your choices are still here.');
		} finally {
			saving = false;
		}
	}
	async function remove() {
		if (!initial) return;
		saving = true;
		try {
			await removeCamera(initial.id).updates(getCameras(), getDetectors());
			await onDone();
		} catch (cause) {
			error = errorMessage(cause, 'Could not remove this camera.');
		} finally {
			saving = false;
		}
	}
</script>

<section class="settings-page">
	<header class="flex flex-wrap items-start justify-between gap-4">
		<div class="flex flex-col gap-2">
			<h1 class="settings-heading">
				{initial ? 'Camera settings' : 'Add your camera'}
			</h1>
			<p class="settings-description">
				{initial
					? 'Update the camera name or connection.'
					: 'Choose a camera or enter its stream URL. Keep it on the same network as this computer.'}
			</p>
		</div>
		{#if !initial && !batchEnabled && candidates.length > 1}
			<Button
				type="button"
				variant="outline"
				disabled={checking || saving}
				onclick={() => {
					batchEnabled = true;
					invalidateCheck();
				}}>Set up several cameras</Button
			>
		{/if}
	</header>

	{#if batchEnabled}
		<CameraBatch
			{candidates}
			{finding}
			{discoveryMessage}
			onfind={find}
			onclose={() => (batchEnabled = false)}
			ondone={onDone}
		/>
	{:else}
		<form
			onsubmit={submit}
			class="grid items-start gap-6 lg:grid-cols-2"
			tabindex="-1"
			aria-label="Connect camera"
		>
			<div class="flex min-w-0 flex-col gap-6">
				{#if changingConnection}
					<CameraDiscovery
						{candidates}
						{address}
						{finding}
						{discoveryMessage}
						{manualAddress}
						disabled={checking || saving}
						onSearch={find}
						onSelect={selectCamera}
						onToggleManual={() => {
							manualAddress = !manualAddress;
							showStreamUri = false;
							connectionChangedInput();
						}}
					/>
					{#if cameraDraftAddress(address) && !manualAddress && !candidates.some((camera) => camera.address === address)}
						<p class="text-sm break-all text-muted-foreground">Camera selected: {address}</p>
					{/if}
					{#if manualAddress}
						<Field.Field>
							<Field.Label for="camera-stream">RTSP URL</Field.Label>
							<InputGroup.Root>
								<InputGroup.Input
									id="camera-stream"
									type={showStreamUri ? 'text' : 'password'}
									bind:value={streamUri}
									oninput={connectionChangedInput}
									disabled={checking || saving}
									placeholder="rtsp://192.168.1.50/stream"
									autocomplete="off"
									spellcheck={false}
									aria-describedby="camera-stream-help"
								/>
								<InputGroup.Addon align="inline-end">
									<InputGroup.Button
										size="icon-sm"
										aria-label={showStreamUri ? 'Hide RTSP URL' : 'Show RTSP URL'}
										title={showStreamUri ? 'Hide RTSP URL' : 'Show RTSP URL'}
										onclick={() => (showStreamUri = !showStreamUri)}
									>
										{#if showStreamUri}<EyeOff />{:else}<Eye />{/if}
									</InputGroup.Button>
								</InputGroup.Addon>
							</InputGroup.Root>
							<Field.Description id="camera-stream-help">
								Paste the full stream URL, including the username and password if required.
							</Field.Description>
						</Field.Field>
					{:else if address}
						<Field.Group>
							<Field.Group class="grid gap-4 sm:grid-cols-2">
								<Field.Field>
									<Field.Label for="camera-username">Camera username</Field.Label>
									<Input
										id="camera-username"
										bind:value={username}
										oninput={credentialsChangedInput}
										disabled={checking || saving}
										autocomplete="off"
									/>
								</Field.Field>
								<Field.Field>
									<Field.Label for="camera-password">Camera password</Field.Label>
									<Input
										id="camera-password"
										type="password"
										bind:value={password}
										oninput={credentialsChangedInput}
										disabled={checking || saving}
										autocomplete="off"
									/>
								</Field.Field>
							</Field.Group>
							<Field.Description
								>Use your camera’s own login, which may differ from its phone app.</Field.Description
							>
						</Field.Group>
					{/if}
					{#if !manualAddress && profiles.length > 1}
						<Field.Field>
							<Field.Label for="camera-profile">Camera channel or stream</Field.Label>
							<NativeSelect.Root
								id="camera-profile"
								bind:value={profileToken}
								disabled={checking || saving}
								onchange={(event) => {
									profileToken = event.currentTarget.value;
									credentialsChangedInput();
									void connect();
								}}
							>
								{#each profiles as profile (profile.token)}<NativeSelect.Option
										value={profile.token}>{profile.name}</NativeSelect.Option
									>{/each}
							</NativeSelect.Root>
						</Field.Field>
					{:else if !manualAddress && initial?.connection?.profileToken && profileToken}
						<Button
							type="button"
							variant="outline"
							class="self-start"
							disabled={checking || saving}
							onclick={chooseChannelAgain}>Choose camera channel again</Button
						>
					{/if}
				{/if}
				{#if check || initial}<Field.Field>
						<Field.Label for="camera-name">Camera name</Field.Label>
						<Input
							id="camera-name"
							bind:value={label}
							disabled={saving}
							required
							placeholder="e.g. Front entrance"
						/>
						<Field.Description>Give this view a name you’ll recognize.</Field.Description>
					</Field.Field>{/if}
				{#if initial && !changingConnection}
					<Button
						type="button"
						variant="outline"
						class="self-start"
						disabled={checking || saving}
						onclick={() => {
							changingConnection = true;
							invalidateCheck();
							manualAddress = !initial.connection;
						}}>Change connection</Button
					>
				{/if}
			</div>

			{#if check}
				<CardOverlay>
					<img
						src={check.previewUrl}
						alt={`${label || 'Camera'} connection preview`}
						class="aspect-video w-full bg-muted object-contain"
					/>
					{#snippet overlay()}
						<div class="flex flex-wrap items-center gap-2">
							<Badge variant="secondary" class="max-w-full text-left whitespace-normal"
								>{label || 'Camera'}</Badge
							>
							<Badge variant="success" role="status">Connected</Badge>
						</div>
					{/snippet}
				</CardOverlay>
			{:else if initial && !changingConnection}
				<CameraPicture id={initial.id} {label} monitored={initial.monitored} />
			{/if}

			{#if error}<div tabindex="-1" bind:this={errorPanel} class="lg:col-span-2">
					<Alert.Root variant="destructive">
						<Alert.Title>Camera needs attention</Alert.Title>
						<Alert.Description>{error}</Alert.Description>
						{#if !connectionChanged}
							<Button
								type="button"
								variant="outline"
								size="sm"
								class="col-start-2 justify-self-start"
								disabled={checking || saving}
								onclick={connect}>Reconnect camera</Button
							>
						{/if}
					</Alert.Root>
				</div>{/if}
			<div class="flex flex-wrap gap-3 lg:col-span-2">
				{#if connectionChanged}
					<Button
						type="submit"
						disabled={checking || saving || !(manualAddress ? streamUri.trim() : address.trim())}
					>
						{checking ? 'Connecting…' : 'Connect camera'}<ArrowRight data-icon="inline-end" />
					</Button>
				{:else}
					<Button type="submit" disabled={checking || saving || !canSave}>
						{checking
							? 'Connecting…'
							: saving
								? 'Saving camera…'
								: initial
									? 'Save changes'
									: 'Save camera'}<ArrowRight data-icon="inline-end" />
					</Button>
				{/if}
				{#if onCancel}<Button type="button" onclick={onCancel} disabled={saving} variant="outline"
						>Cancel</Button
					>{/if}
			</div>
			{#if initial}
				<details class="lg:col-span-2">
					<summary class="cursor-pointer text-sm text-muted-foreground">Remove this camera</summary>
					<p class="my-3 text-sm">
						Monitoring and alerts for {label} will stop. Existing recordings stay on this computer.
					</p>
					<Field.Field orientation="horizontal">
						<Checkbox id="confirm-remove-camera" bind:checked={confirmingRemoval} />
						<Field.Label for="confirm-remove-camera"
							>Stop monitoring and remove this camera</Field.Label
						>
					</Field.Field>
					<Button
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

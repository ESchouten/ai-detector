<script lang="ts">
	import { errorMessage } from '$lib/remote-errors';
	import { onDestroy, onMount, tick, untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Badge } from '$lib/components/ui/badge';
	import { ArrowRight, Search } from '@lucide/svelte';
	import * as Field from '$lib/components/ui/field';
	import * as Alert from '$lib/components/ui/alert';
	import * as NativeSelect from '$lib/components/ui/native-select';
	import * as RadioGroup from '$lib/components/ui/radio-group';
	import CameraPicture from './camera-picture.svelte';
	import CardOverlay from './card-overlay.svelte';
	import CameraBatch from './camera-batch.svelte';
	import SetupSteps from './setup-steps.svelte';
	import type { BatchCamera, BatchConnection } from '$lib/camera-batch';
	import type { StreamMeta } from '$lib/schema';
	import { discoverCameras, getCameraConnection } from '$lib/remote/camera.remote';
	import { checkCameraRecording } from '$lib/camera-check';
	import { cameraDraftAddress, cameraEditConnection } from '$lib/cameras';
	import { getCameras, removeCamera, saveCamera } from '$lib/remote/stream.remote';
	import { getDetectors } from '$lib/remote/detector.remote';

	let {
		initial,
		setupMode = false,
		hasCameras = false
	}: {
		initial?: StreamMeta & { id: string; monitored: boolean };
		setupMode?: boolean;
		hasCameras?: boolean;
	} = $props();
	const returnTo = $derived(setupMode ? '/setup?step=cameras' : '/streams');
	let label = $state(untrack(() => initial?.label ?? ''));
	let source = $state(untrack(() => initial?.source ?? ''));
	const editing = untrack(() => cameraEditConnection(initial?.source ?? ''));
	let address = $state(untrack(() => initial?.connection?.address ?? ''));
	let username = $state(editing.username);
	let password = $state('');
	let streamUri = $state(untrack(() => initial?.source ?? ''));
	let profiles = $state<{ token: string; name: string }[]>([]);
	let profileToken = $state(untrack(() => initial?.connection?.profileToken ?? ''));
	let verifiedConnection = $state<StreamMeta['connection']>(untrack(() => initial?.connection));
	let manualAddress = $state(false);
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
	let saved = $state<{ id: string; monitored: boolean }>();
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
				if (typeof parsed.label === 'string') label = parsed.label;
				if (typeof parsed.address === 'string') address = cameraDraftAddress(parsed.address) ?? '';
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
					address: cameraDraftAddress(address)
				})
			);
	});

	function invalidateCheck() {
		check = undefined;
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
	async function openBatchCamera(camera: BatchCamera) {
		if (!camera.connection || !camera.login) return;
		saved = undefined;
		batchAddress = camera.address;
		label = camera.name;
		address = camera.address;
		username = camera.login.username;
		password = camera.login.password;
		source = '';
		streamUri = '';
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
		await connect();
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
					: 'No cameras found. Enter its stream URL manually, or check that the camera and this computer use the same network.');
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
	async function connect() {
		const controller = new AbortController();
		checkController = controller;
		checking = true;
		invalidateCheck();
		try {
			const connection =
				initial && !changingConnection
					? { source, profiles, connection: initial.connection }
					: (preparedConnection ??
						(await getCameraConnection(
							manualAddress
								? { streamUri }
								: { address, username, password, ...(profileToken ? { profileToken } : {}) }
						)));
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
			saved = await saveCamera({
				label,
				source,
				id: initial?.id,
				mode: initial ? 'keep' : 'view-only',
				checkId: check?.checkId,
				...(changingConnection ? { connection: verifiedConnection ?? null } : {})
			}).updates(getCameras(), getDetectors());
			if (batchAddress) {
				const savedId = saved.id;
				batchQueue = batchQueue.map((camera) =>
					camera.address === batchAddress
						? { address: camera.address, name: label, state: 'saved', savedId }
						: camera
				);
			}
			sessionStorage.removeItem('camera-setup');
			if (!batchEnabled) await goto(resolve(returnTo));
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
			await goto(resolve(returnTo));
		} catch (cause) {
			error = errorMessage(cause, 'Could not remove this camera.');
		} finally {
			saving = false;
		}
	}
	function addAnother() {
		if (initial) {
			void goto(resolve(setupMode ? '/streams/add?setup=1' : '/streams/add'));
			return;
		}
		saved = undefined;
		label = '';
		source = '';
		address = '';
		username = '';
		password = '';
		streamUri = '';
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

<section class="settings-page">
	{#if setupMode}<SetupSteps current="cameras" {hasCameras} />{/if}
	<header class="flex flex-wrap items-start justify-between gap-4">
		<div class="flex flex-col gap-2">
			<h1 class="settings-heading">
				{saved ? `${label} is saved` : initial ? 'Camera settings' : 'Add your camera'}
			</h1>
			<p class="settings-description">
				{saved
					? 'Add another camera, or continue to choose your detectors.'
					: initial
						? 'Update the camera name or connection.'
						: 'Choose a camera or enter its stream URL. Keep it on the same network as this computer.'}
			</p>
		</div>
		{#if !initial && !batchEnabled && !saved}
			<Button
				type="button"
				variant="outline"
				disabled={checking || saving}
				onclick={() => {
					batchEnabled = true;
					batchAddress = '';
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

	{#if saved && batchEnabled}
		<div class="flex max-w-2xl flex-col gap-5">
			<CameraPicture id={saved.id} {label} />
			<div class="flex flex-wrap gap-3">
				{#if nextBatchCamera}
					<Button
						type="button"
						disabled={saving || checking || batchConnecting}
						onclick={() => nextBatchCamera && openBatchCamera(nextBatchCamera)}
						>Add next camera <ArrowRight data-icon="inline-end" /></Button
					>
				{/if}
				<Button
					href={resolve(setupMode ? '/setup?step=detectors' : '/streams')}
					variant={nextBatchCamera ? 'outline' : 'default'}
				>
					{setupMode ? 'Continue to detectors' : 'Done'}
				</Button>
			</div>
		</div>
	{:else if !batchEnabled || batchAddress}
		<form
			onsubmit={submit}
			class="grid items-start gap-6 lg:grid-cols-2"
			bind:this={cameraForm}
			tabindex="-1"
			aria-label="Connect camera"
		>
			<div class="flex min-w-0 flex-col gap-6">
				{#if changingConnection}
					{#if !batchAddress}
						<section aria-labelledby="camera-discovery-title" class="flex flex-col gap-4">
							<div class="flex flex-col gap-2">
								<div class="flex flex-wrap items-center justify-between gap-3">
									<h2 id="camera-discovery-title" class="font-medium">Available cameras</h2>
									<Button
										type="button"
										variant="outline"
										size="sm"
										disabled={finding || checking || saving}
										onclick={find}
									>
										<Search data-icon="inline-start" />{finding ? 'Searching…' : 'Search again'}
									</Button>
								</div>
								{#if discoveryMessage}<p role="status" class="text-sm text-muted-foreground">
										{discoveryMessage}
									</p>{/if}
							</div>
							{#if candidates.length}
								<RadioGroup.Root
									value={address}
									aria-label="Discovered cameras"
									disabled={checking || saving}
									onValueChange={(value) => {
										const previousName = candidates.find(
											(camera) => camera.address === address
										)?.name;
										address = value;
										manualAddress = false;
										if (!label || label === previousName)
											label = candidates.find((camera) => camera.address === value)?.name ?? '';
										connectionChangedInput();
									}}
								>
									{#each candidates as camera, index (camera.address)}
										<Field.Field orientation="horizontal">
											<RadioGroup.Item id={`camera-choice-${index}`} value={camera.address} />
											<Field.Label for={`camera-choice-${index}`} class="min-w-0 cursor-pointer">
												<Field.Content>
													<Field.Title>{camera.name}</Field.Title>
													<Field.Description class="break-all">{camera.address}</Field.Description>
												</Field.Content>
											</Field.Label>
										</Field.Field>
									{/each}
								</RadioGroup.Root>
							{/if}
							<Button
								type="button"
								variant="outline"
								class="self-start"
								aria-expanded={manualAddress}
								disabled={checking || saving}
								onclick={() => {
									manualAddress = !manualAddress;
									connectionChangedInput();
								}}>{manualAddress ? 'Hide manual entry' : 'Enter camera manually'}</Button
							>
						</section>
					{/if}
					{#if cameraDraftAddress(address) && !manualAddress && !candidates.some((camera) => camera.address === address)}
						<p class="text-sm break-all text-muted-foreground">Camera selected: {address}</p>
					{/if}
					{#if manualAddress}
						<Field.Field>
							<Field.Label for="camera-stream">RTSP URL</Field.Label>
							<Input
								id="camera-stream"
								type="password"
								bind:value={streamUri}
								oninput={connectionChangedInput}
								disabled={checking || saving}
								placeholder="rtsp://192.168.1.50/stream"
								autocomplete="off"
								aria-describedby="camera-stream-help"
							/>
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
				<Field.Field>
					<Field.Label for="camera-name">Camera name</Field.Label>
					<Input
						id="camera-name"
						bind:value={label}
						disabled={saving}
						required
						placeholder="e.g. Front entrance"
					/>
				</Field.Field>
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
							<Badge variant="secondary" role="status">Connected</Badge>
						</div>
					{/snippet}
				</CardOverlay>
			{:else if initial && !changingConnection}
				<CameraPicture id={initial.id} {label} />
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
				<Button href={resolve(returnTo)} variant="outline">Cancel</Button>
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

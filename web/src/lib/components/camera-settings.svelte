<script lang="ts">
	import { errorMessage } from '$lib/remote-errors';
	import { onDestroy, onMount, untrack } from 'svelte';
	import { resolve } from '$app/paths';
	import { toast } from 'svelte-sonner';
	import { Button, buttonVariants } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import * as Field from '$lib/components/ui/field';
	import * as Alert from '$lib/components/ui/alert';
	import * as AlertDialog from '$lib/components/ui/alert-dialog';
	import * as NativeSelect from '$lib/components/ui/native-select';
	import CameraDiscovery from './camera-discovery.svelte';
	import CameraPicture from './camera-picture.svelte';
	import Pill from './pill.svelte';
	import SecretInput from './secret-input.svelte';
	import type { StreamMeta } from '$lib/schema';
	import { checkCameraRecording } from '$lib/camera-check';
	import { cameraUsername } from '$lib/cameras';
	import {
		discoverCameras,
		getCameraConnection,
		getCameras,
		removeCamera,
		saveCamera
	} from '$lib/remote/camera.remote';
	import { getDetectors } from '$lib/remote/detector.remote';

	// Rename, reconnect or remove one saved camera. Its detectors are chosen under Detectors.
	let {
		initial,
		onDone
	}: {
		initial: StreamMeta & { id: string; label: string; monitored: boolean };
		onDone: () => Promise<void>;
	} = $props();
	let label = $state(untrack(() => initial.label));
	let source = $state(untrack(() => initial.source));
	let address = $state(untrack(() => initial.connection?.address ?? ''));
	let username = $state(untrack(() => cameraUsername(initial.source)));
	let password = $state('');
	let streamUri = $state(untrack(() => initial.source));
	let profiles = $state<{ token: string; name: string }[]>([]);
	let profileToken = $state(untrack(() => initial.connection?.profileToken ?? ''));
	let verifiedConnection = $state<StreamMeta['connection']>(untrack(() => initial.connection));
	let manualAddress = $state(false);
	let changingConnection = $state(false);
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
	const connectionChanged = $derived(changingConnection && !check);
	const canSave = $derived(Boolean(label.trim()) && !connectionChanged);

	onMount(() => {
		// Imported cameras have not shown a picture in this installation yet.
		if (!initial.setup?.pictureVerifiedAt) void connect();
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
	function chooseChannelAgain() {
		source = '';
		verifiedConnection = undefined;
		connectionChangedInput();
	}
	function selectCamera(value: string) {
		address = value;
		manualAddress = false;
		connectionChangedInput();
	}
	async function find() {
		finding = true;
		error = '';
		try {
			const result = await discoverCameras();
			candidates = result.cameras;
			discoveryMessage = result.message ?? '';
		} catch (cause) {
			if (!address) manualAddress = true;
			discoveryMessage = errorMessage(
				cause,
				'Camera search failed. Check the network and try again.'
			);
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
			const connection = !changingConnection
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
				id: initial.id,
				checkId: check?.checkId,
				...(changingConnection ? { connection: verifiedConnection ?? null } : {})
			}).updates(getCameras(), getDetectors());
			toast.success('Camera saved.');
			await onDone();
		} catch (cause) {
			error = errorMessage(cause, 'The camera could not be saved. Your choices are still here.');
		} finally {
			saving = false;
		}
	}
	async function remove() {
		saving = true;
		try {
			await removeCamera(initial.id).updates(getCameras(), getDetectors());
			toast.success('Camera removed.');
			await onDone();
		} catch (cause) {
			error = errorMessage(cause, 'Could not remove this camera.');
		} finally {
			saving = false;
		}
	}
</script>

<div class="grid items-start gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(20rem,2fr)]">
	<div class="flex min-w-0 flex-col gap-3">
		{#if check}
			<div class="relative aspect-video overflow-hidden rounded-xl bg-media">
				<img
					src={check.previewUrl}
					alt={`${label || 'Camera'} connection preview`}
					class="size-full object-contain"
				/>
				<div class="absolute top-2.5 left-2.5"><Pill tone="ok" role="status">Connected</Pill></div>
			</div>
		{:else if !changingConnection}
			<CameraPicture id={initial.id} {label} monitored={initial.monitored}>
				{#snippet caption()}{/snippet}
			</CameraPicture>
		{:else}
			<div
				class="flex aspect-video items-center justify-center rounded-xl bg-media px-6 text-center text-sm text-media-foreground/70"
			>
				{checking ? 'Connecting…' : 'Connect to see the new picture.'}
			</div>
		{/if}
	</div>

	<form onsubmit={submit} class="flex min-w-0 flex-col gap-6" aria-label="Camera settings">
		<Field.Field>
			<Field.Label for="camera-name">Camera name</Field.Label>
			<Input
				id="camera-name"
				bind:value={label}
				disabled={saving}
				required
				placeholder="Example: Calving pen"
			/>
		</Field.Field>

		{#if changingConnection}
			<div class="panel flex flex-col gap-5 p-4">
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
						connectionChangedInput();
					}}
				/>
				{#if address && !manualAddress && !candidates.some((camera) => camera.address === address)}
					<p class="text-sm break-all text-muted-foreground">Camera selected: {address}</p>
				{/if}
				{#if manualAddress}
					<Field.Field>
						<Field.Label for="camera-stream">RTSP URL</Field.Label>
						<SecretInput
							id="camera-stream"
							name="stream URL"
							bind:value={streamUri}
							oninput={connectionChangedInput}
							disabled={checking || saving}
							placeholder="rtsp://192.168.1.50/stream"
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
									oninput={invalidateCheck}
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
									oninput={invalidateCheck}
									disabled={checking || saving}
									autocomplete="off"
								/>
							</Field.Field>
						</Field.Group>
						<Field.Description>
							The camera’s own login, which may differ from its phone app.
						</Field.Description>
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
								invalidateCheck();
								void connect();
							}}
						>
							{#each profiles as profile (profile.token)}
								<NativeSelect.Option value={profile.token}>{profile.name}</NativeSelect.Option>
							{/each}
						</NativeSelect.Root>
					</Field.Field>
				{:else if !manualAddress && initial.connection?.profileToken && profileToken}
					<Button
						variant="outline"
						size="sm"
						class="self-start"
						disabled={checking || saving}
						onclick={chooseChannelAgain}>Choose camera channel again</Button
					>
				{/if}
			</div>
		{/if}

		{#if error}
			<div tabindex="-1" bind:this={errorPanel} class="outline-none">
				<Alert.Root variant="destructive">
					<Alert.Title>Camera needs attention</Alert.Title>
					<Alert.Description>{error}</Alert.Description>
					{#if !connectionChanged}
						<Button
							variant="outline"
							size="sm"
							class="col-start-2 mt-2 justify-self-start"
							disabled={checking || saving}
							onclick={connect}>Reconnect camera</Button
						>
					{/if}
				</Alert.Root>
			</div>
		{/if}

		<div class="flex flex-wrap gap-3">
			{#if connectionChanged}
				<Button
					type="submit"
					disabled={checking || saving || !(manualAddress ? streamUri.trim() : address.trim())}
				>
					{checking ? 'Connecting…' : 'Connect camera'}
				</Button>
				<Button
					variant="outline"
					disabled={checking || saving}
					onclick={() => {
						changingConnection = false;
						source = initial.source;
						invalidateCheck();
					}}>Keep current connection</Button
				>
			{:else}
				<Button type="submit" disabled={checking || saving || !canSave}>
					{checking ? 'Connecting…' : saving ? 'Saving…' : 'Save changes'}
				</Button>
				{#if !changingConnection}
					<Button
						variant="outline"
						disabled={checking || saving}
						onclick={() => {
							changingConnection = true;
							invalidateCheck();
							manualAddress = !initial.connection;
							if (!candidates.length) void find();
						}}>Change connection</Button
					>
				{/if}
			{/if}
		</div>

		<div class="flex flex-col items-start gap-2 border-t pt-5">
			<AlertDialog.Root>
				<AlertDialog.Trigger
					type="button"
					class={buttonVariants({ variant: 'ghost', size: 'sm' }) +
						' -ml-2.5 text-danger-foreground hover:text-danger-foreground'}
					disabled={saving}>Remove this camera…</AlertDialog.Trigger
				>
				<AlertDialog.Content>
					<AlertDialog.Header>
						<AlertDialog.Title>Remove “{initial.label}”?</AlertDialog.Title>
						<AlertDialog.Description>
							Monitoring and alerts for this camera will stop. Its existing recordings stay on this
							computer.
						</AlertDialog.Description>
					</AlertDialog.Header>
					<AlertDialog.Footer>
						<AlertDialog.Cancel type="button">Keep camera</AlertDialog.Cancel>
						<AlertDialog.Action
							type="button"
							class={buttonVariants({ variant: 'destructive' })}
							onclick={remove}>Remove camera</AlertDialog.Action
						>
					</AlertDialog.Footer>
				</AlertDialog.Content>
			</AlertDialog.Root>
		</div>
	</form>
</div>

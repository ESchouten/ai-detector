<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import { ArrowRight, Check, LoaderCircle, Search, X } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import * as Alert from '$lib/components/ui/alert';
	import * as Field from '$lib/components/ui/field';
	import * as NativeSelect from '$lib/components/ui/native-select';
	import Pill from './pill.svelte';
	import SecretInput from './secret-input.svelte';
	import {
		connectCameraBatch,
		type BatchCamera,
		type CameraLogin,
		type CheckedConnection
	} from '$lib/camera-batch';
	import { checkConnection } from '$lib/camera-check';
	import type { DiscoveredCamera } from '$lib/cameras';
	import { uniqueLabel } from '$lib/configuration';
	import { plural } from '$lib/format';
	import { errorMessage } from '$lib/remote-errors';
	import {
		discoverCameras,
		getCameraConnection,
		getCameras,
		saveCamera
	} from '$lib/remote/camera.remote';

	// One flow for one camera or several: find them, check each picture, name them, add them.
	let {
		onDone,
		onCancel
	}: {
		onDone: () => void | Promise<void>;
		onCancel?: () => void | Promise<void>;
	} = $props();

	const existing = await getCameras();
	const known = new Set(existing.map((camera) => camera.connection?.address).filter(Boolean));
	let candidates = $state<DiscoveredCamera[]>([]);
	let discoveryMessage = $state('');
	let finding = $state(false);
	let selected = $state<string[]>([]);
	let username = $state('admin');
	let password = $state('');
	// Many cameras still have the login they came with, so that is tried before asking for one.
	let askLogin = $state(false);
	let manual = $state(false);
	let streamUri = $state('');
	let manualError = $state('');
	let manualCount = 0;
	let queue = $state<BatchCamera[]>([]);
	let choosing = $state(true);
	let connecting = $state(false);
	let saving = $state(false);
	let controller: AbortController | undefined;
	onDestroy(() => controller?.abort());
	const checks = resolve('/camera-checks');

	const busy = $derived(connecting || saving);
	const pending = $derived(queue.filter((camera) => camera.state !== 'saved'));
	const ready = $derived(queue.filter((camera) => camera.state === 'ready'));
	const failed = $derived(queue.some((camera) => camera.state === 'failed'));
	const labels = {
		waiting: 'Waiting',
		connecting: 'Connecting…',
		ready: 'Connected',
		failed: 'Could not connect',
		saved: 'Added'
	};

	onMount(() => void find());

	async function find() {
		finding = true;
		try {
			const result = await discoverCameras();
			candidates = result.cameras;
			if (!candidates.length) manual = true;
			// Most people want every camera that was found; leaving one out is the exception.
			else if (!selected.length && !queue.length)
				selected = candidates
					.map((camera) => camera.address)
					.filter((address) => !known.has(address));
			discoveryMessage = result.message ?? '';
		} catch (cause) {
			manual = true;
			discoveryMessage = errorMessage(
				cause,
				'Camera search failed. Check the network and try again.'
			);
		} finally {
			finding = false;
		}
	}

	function select(address: string, checked: boolean) {
		selected = checked ? [...selected, address] : selected.filter((value) => value !== address);
	}
	function update(updated: BatchCamera) {
		queue = queue.map((camera) => (camera.address === updated.address ? updated : camera));
	}
	function remove(address: string) {
		queue = queue.filter((camera) => camera.address !== address);
		selected = selected.filter((value) => value !== address);
		if (!queue.some((camera) => camera.state !== 'saved')) choosing = true;
	}
	function start(): AbortSignal {
		controller = new AbortController();
		connecting = true;
		return controller.signal;
	}

	async function connect() {
		const queued = new Set(queue.map((camera) => camera.address));
		queue = [
			...queue,
			...candidates
				.filter((camera) => selected.includes(camera.address) && !queued.has(camera.address))
				.map((camera) => ({ ...camera, state: 'waiting' as const }))
		];
		const signal = start();
		choosing = false;
		await connectCameraBatch(
			queue.filter((camera) => selected.includes(camera.address)),
			{ username, password },
			async (input) => checkConnection(await getCameraConnection(input), signal, checks),
			update,
			signal
		);
		if (signal.aborted) return;
		connecting = false;
		if (!askLogin && queue.some((camera) => camera.state === 'failed')) {
			askLogin = true;
			choosing = true;
		}
	}

	async function connectManual(event: SubmitEvent) {
		event.preventDefault();
		manualError = '';
		const signal = start();
		try {
			const connection = await checkConnection(
				await getCameraConnection({ streamUri }),
				signal,
				checks
			);
			const used = new Set([
				...existing.map((camera) => camera.label),
				...queue.map((camera) => camera.name)
			]);
			queue = [
				...queue,
				{
					address: `manual:${++manualCount}`,
					name: uniqueLabel('Camera', used),
					state: 'ready',
					connection
				}
			];
			streamUri = '';
			choosing = false;
		} catch (cause) {
			if (!signal.aborted)
				manualError = errorMessage(
					cause,
					'Could not connect to the camera. Check the stream URL and try again.'
				);
		} finally {
			if (!signal.aborted) connecting = false;
		}
	}

	/** Show a fresh picture for a camera in the list, from the connection `reach` gives. */
	async function recheck(
		camera: BatchCamera,
		reach: (signal: AbortSignal) => Promise<CheckedConnection>
	) {
		const signal = start();
		try {
			update({ ...camera, state: 'ready', error: undefined, connection: await reach(signal) });
		} catch (cause) {
			if (!signal.aborted)
				update({
					...camera,
					state: 'failed',
					error: errorMessage(cause, 'Could not check this picture. Try again.')
				});
		} finally {
			if (!signal.aborted) connecting = false;
		}
	}
	function refreshPicture(camera: BatchCamera, current: CheckedConnection) {
		return recheck(camera, (signal) => checkConnection(current, signal, checks));
	}
	/** Another stream of the same camera, opened with the login that reached it. */
	function showStream(camera: BatchCamera, login: CameraLogin, profileToken: string) {
		return recheck(camera, async (signal) =>
			checkConnection(
				{
					...(await getCameraConnection({ address: camera.address, ...login, profileToken })),
					login
				},
				signal,
				checks
			)
		);
	}

	async function save() {
		saving = true;
		for (const camera of ready) {
			const { connection } = camera;
			try {
				const saved = await saveCamera({
					label: camera.name.trim(),
					source: connection.source,
					checkId: connection.check.checkId,
					connection: connection.connection
				});
				update({ ...camera, state: 'saved', savedId: saved.id, error: undefined });
			} catch (cause) {
				update({ ...camera, error: errorMessage(cause, 'Could not add this camera. Try again.') });
			}
		}
		try {
			await getCameras().refresh();
		} finally {
			saving = false;
		}
		if (queue.every((camera) => camera.state === 'saved')) await onDone();
	}
</script>

<div class="flex flex-col gap-6">
	{#if choosing}
		<section class="panel flex flex-col gap-5 p-5" aria-labelledby="camera-find-title">
			<div class="flex flex-wrap items-center justify-between gap-3">
				<h2 id="camera-find-title" class="text-base font-semibold">Cameras on your network</h2>
				<Button variant="outline" size="sm" disabled={finding || busy} onclick={find}>
					{#if finding}<LoaderCircle
							data-icon="inline-start"
							class="animate-spin"
							aria-hidden="true"
						/>{:else}<Search data-icon="inline-start" aria-hidden="true" />{/if}
					{finding ? 'Searching…' : 'Search again'}
				</Button>
			</div>
			{#if finding && !candidates.length}
				<p role="status" class="text-sm text-muted-foreground">Looking for cameras…</p>
			{/if}
			{#if discoveryMessage}
				<p role="status" class="text-sm text-muted-foreground">{discoveryMessage}</p>
			{/if}
			{#if candidates.length}
				<ul class="-mx-2 flex flex-col">
					{#each candidates as camera, index (camera.address)}
						{@const item = queue.find((queued) => queued.address === camera.address)}
						<li>
							<label
								for={`discovered-${index}`}
								class="flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2.5 hover:bg-accent has-disabled:cursor-default has-disabled:hover:bg-transparent"
							>
								<Checkbox
									id={`discovered-${index}`}
									checked={selected.includes(camera.address)}
									disabled={busy || item?.state === 'saved'}
									onCheckedChange={(checked) => select(camera.address, checked)}
								/>
								<span class="flex min-w-0 flex-1 flex-col">
									<span class="text-sm font-medium">{camera.name}</span>
									<span class="text-xs break-all text-muted-foreground">{camera.address}</span>
								</span>
								{#if item?.state === 'saved' || known.has(camera.address)}
									<Pill>Already added</Pill>
								{/if}
							</label>
						</li>
					{/each}
				</ul>
				{#if selected.length && askLogin}
					<Field.Group class="border-t pt-5">
						<Field.Group class="grid gap-4 sm:grid-cols-2">
							<Field.Field>
								<Field.Label for="camera-username">Camera username</Field.Label>
								<Input
									id="camera-username"
									bind:value={username}
									disabled={busy}
									autocomplete="off"
								/>
							</Field.Field>
							<Field.Field>
								<Field.Label for="camera-password">Camera password</Field.Label>
								<Input
									id="camera-password"
									type="password"
									bind:value={password}
									disabled={busy}
									autocomplete="off"
								/>
							</Field.Field>
						</Field.Group>
						<Field.Description>
							The camera’s own login, which may differ from its phone app.
							{selected.length > 1 ? 'Select cameras that share this login.' : ''}
						</Field.Description>
					</Field.Group>
				{/if}
				<div class="flex flex-wrap items-center gap-2">
					<Button disabled={busy || finding || !selected.length} onclick={connect}>
						{failed
							? 'Try again'
							: plural(selected.length || 1, ['Connect # camera', 'Connect # cameras'])}
						<ArrowRight data-icon="inline-end" aria-hidden="true" />
					</Button>
					{#if !manual}
						<Button variant="ghost" disabled={busy} onclick={() => (manual = true)}>
							Enter a stream URL instead
						</Button>
					{/if}
				</div>
			{/if}
		</section>

		{#if manual}
			<form
				class="panel flex flex-col gap-4 p-5"
				aria-labelledby="camera-manual-title"
				onsubmit={connectManual}
			>
				<h2 id="camera-manual-title" class="text-base font-semibold">Enter a stream URL</h2>
				<Field.Field>
					<Field.Label for="camera-stream">RTSP URL</Field.Label>
					<SecretInput
						id="camera-stream"
						name="stream URL"
						bind:value={streamUri}
						disabled={busy}
						placeholder="rtsp://192.168.1.50/stream"
						aria-describedby="camera-stream-help"
					/>
					<Field.Description id="camera-stream-help">
						Paste the full stream URL, including the username and password if the camera needs them.
					</Field.Description>
				</Field.Field>
				{#if manualError}
					<Alert.Root variant="destructive">
						<Alert.Title>Camera needs attention</Alert.Title>
						<Alert.Description>{manualError}</Alert.Description>
					</Alert.Root>
				{/if}
				<div>
					<Button
						type="submit"
						variant={candidates.length ? 'outline' : 'default'}
						disabled={busy || !streamUri.trim()}
					>
						{connecting ? 'Connecting…' : 'Connect camera'}
						<ArrowRight data-icon="inline-end" aria-hidden="true" />
					</Button>
				</div>
			</form>
		{/if}
	{/if}

	{#if pending.length || (!choosing && queue.length)}
		<section class="flex flex-col gap-4" aria-labelledby="camera-review-title">
			<div class="flex flex-col gap-1">
				<h2 id="camera-review-title" class="text-base font-semibold">
					{pending.length === 1 ? 'Check the picture' : 'Check the pictures'}
				</h2>
				<p class="text-sm text-muted-foreground">
					Give each camera a name you’ll recognize. A short test recording is checked for you.
				</p>
			</div>
			<ul class="grid items-start gap-5 sm:grid-cols-2">
				{#each queue as camera, index (camera.address)}
					<li class="flex min-w-0 flex-col gap-3">
						<div class="relative aspect-video overflow-hidden rounded-xl bg-media">
							{#if camera.connection}
								<img
									src={camera.connection.check.previewUrl}
									alt={`${camera.name} connection preview`}
									class="size-full object-contain"
								/>
							{:else if camera.state === 'connecting' || camera.state === 'waiting'}
								<div class="flex size-full items-center justify-center text-media-foreground/70">
									<LoaderCircle class="size-6 animate-spin" aria-hidden="true" />
								</div>
							{/if}
							<div class="absolute top-2.5 left-2.5">
								<Pill
									role="status"
									tone={camera.state === 'failed'
										? 'bad'
										: camera.state === 'ready' || camera.state === 'saved'
											? 'ok'
											: 'neutral'}
								>
									{#if camera.state === 'saved'}<Check aria-hidden="true" />{/if}
									{labels[camera.state]}
								</Pill>
							</div>
							{#if camera.state !== 'saved'}
								<Button
									variant="secondary"
									size="icon-sm"
									class="absolute top-2 right-2"
									disabled={busy}
									onclick={() => remove(camera.address)}
									aria-label={`Leave out ${camera.name}`}
									title="Leave out"><X aria-hidden="true" /></Button
								>
							{/if}
						</div>
						{#if camera.state === 'ready' || camera.state === 'saved'}
							<Field.Field>
								<Field.Label for={`camera-name-${index}`}>Camera name</Field.Label>
								<Input
									id={`camera-name-${index}`}
									bind:value={camera.name}
									disabled={busy || camera.state === 'saved'}
									required
									placeholder="e.g. Calving pen"
								/>
							</Field.Field>
						{:else}
							<p class="text-sm font-medium break-words">{camera.name}</p>
						{/if}
						{#if camera.connection?.login && camera.connection.profiles.length > 1}
							{@const login = camera.connection.login}
							<Field.Field>
								<Field.Label for={`camera-profile-${index}`}>Camera channel or stream</Field.Label>
								<NativeSelect.Root
									id={`camera-profile-${index}`}
									value={camera.connection.connection?.profileToken ?? ''}
									disabled={busy || camera.state === 'saved'}
									onchange={(event) => showStream(camera, login, event.currentTarget.value)}
								>
									{#each camera.connection.profiles as profile (profile.token)}
										<NativeSelect.Option value={profile.token}>{profile.name}</NativeSelect.Option>
									{/each}
								</NativeSelect.Root>
							</Field.Field>
						{/if}
						{#if camera.error}
							<p role="alert" class="text-sm break-words text-danger-foreground">{camera.error}</p>
							{#if camera.state === 'ready'}
								{@const connection = camera.connection}
								<Button
									variant="outline"
									size="sm"
									class="self-start"
									disabled={busy}
									onclick={() => refreshPicture(camera, connection)}>Refresh picture</Button
								>
							{/if}
						{/if}
					</li>
				{/each}
			</ul>
		</section>
	{/if}

	{#if !choosing || onCancel}
		<div class="flex flex-wrap gap-3">
			{#if !choosing}
				<Button
					disabled={busy || !ready.length || ready.some((camera) => !camera.name.trim())}
					onclick={save}
				>
					{#if saving}<LoaderCircle
							data-icon="inline-start"
							class="animate-spin"
							aria-hidden="true"
						/>{/if}
					{saving ? 'Adding…' : plural(ready.length || 1, ['Add # camera', 'Add # cameras'])}
				</Button>
				<Button variant="outline" disabled={busy} onclick={() => (choosing = true)}>
					{failed ? 'Change login and retry' : 'Add more cameras'}
				</Button>
			{/if}
			{#if queue.some((camera) => camera.state === 'saved')}
				<Button variant="ghost" disabled={busy} onclick={onDone}>Done</Button>
			{:else if onCancel}
				<Button variant="ghost" disabled={saving} onclick={onCancel}>Cancel</Button>
			{/if}
		</div>
	{/if}
</div>

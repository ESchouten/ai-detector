<script lang="ts">
	import { onDestroy } from 'svelte';
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Badge } from '$lib/components/ui/badge';
	import * as NativeSelect from '$lib/components/ui/native-select';
	import * as Field from '$lib/components/ui/field';
	import CardOverlay from './card-overlay.svelte';
	import { getCameraConnection } from '$lib/remote/camera.remote';
	import { getCameras, saveCamera } from '$lib/remote/stream.remote';
	import { checkCameraRecording } from '$lib/camera-check';
	import { errorMessage } from '$lib/remote-errors';
	import type { DiscoveredCamera } from '$lib/cameras';
	import { connectCameraBatch, type BatchCamera } from '$lib/camera-batch';
	let {
		candidates,
		finding,
		discoveryMessage,
		onfind,
		onclose,
		ondone
	}: {
		candidates: DiscoveredCamera[];
		finding: boolean;
		discoveryMessage: string;
		onfind: () => Promise<void>;
		onclose: () => void;
		ondone: () => void | Promise<void>;
	} = $props();
	let queue = $state<BatchCamera[]>([]);
	let selected = $state<string[]>([]);
	let username = $state('admin');
	let password = $state('');
	let choosing = $state(true);
	let connecting = $state(false);
	let saving = $state(false);
	let controller: AbortController | undefined;
	const busy = $derived(connecting || saving || finding);
	const failures = $derived(queue.some((camera) => camera.state === 'failed'));
	const ready = $derived(
		queue.filter((camera) => camera.state === 'ready' && selected.includes(camera.address))
	);
	const labels = {
		waiting: 'Waiting',
		connecting: 'Connecting…',
		ready: 'Connected',
		failed: 'Could not connect',
		saved: 'Added'
	};
	onDestroy(() => controller?.abort());
	function select(address: string, checked: boolean) {
		selected = checked ? [...selected, address] : selected.filter((value) => value !== address);
	}
	async function connect() {
		const known = new Set(queue.map((camera) => camera.address));
		queue = [
			...queue,
			...candidates
				.filter((camera) => selected.includes(camera.address) && !known.has(camera.address))
				.map((camera) => ({ ...camera, state: 'waiting' as const }))
		];
		const operation = new AbortController();
		controller = operation;
		connecting = true;
		choosing = false;
		await connectCameraBatch(
			queue.filter((camera) => selected.includes(camera.address)),
			{ username, password },
			async (input) => {
				const connection = await getCameraConnection(input);
				operation.signal.throwIfAborted();
				const check = await checkCameraRecording(
					connection.source,
					operation.signal,
					resolve('/camera-checks')
				);
				return { ...connection, source: check.source, check };
			},
			(updated) => {
				queue = queue.map((camera) => (camera.address === updated.address ? updated : camera));
			},
			operation.signal
		);
		if (!operation.signal.aborted) connecting = false;
	}
	async function refreshPicture(camera: BatchCamera, profileToken?: string) {
		const operation = new AbortController();
		controller = operation;
		connecting = true;
		try {
			const connection = profileToken
				? await getCameraConnection({ address: camera.address, ...camera.login!, profileToken })
				: camera.connection!;
			operation.signal.throwIfAborted();
			const check = await checkCameraRecording(
				connection.source,
				operation.signal,
				resolve('/camera-checks')
			);
			queue = queue.map((item) =>
				item.address === camera.address
					? {
							...item,
							state: 'ready',
							error: undefined,
							connection: { ...connection, source: check.source, check }
						}
					: item
			);
		} catch (cause) {
			if (!operation.signal.aborted)
				queue = queue.map((item) =>
					item.address === camera.address
						? {
								...item,
								state: 'failed',
								error: errorMessage(cause, 'Could not check this picture. Try again.')
							}
						: item
				);
		} finally {
			if (!operation.signal.aborted) connecting = false;
		}
	}

	async function save() {
		saving = true;
		for (const camera of ready) {
			const connection = camera.connection!;
			try {
				const saved = await saveCamera({
					label: camera.name.trim(),
					source: connection.source,
					mode: 'view-only',
					checkId: connection.check!.checkId,
					connection: connection.connection
				});
				queue = queue.map((item) =>
					item.address === camera.address
						? { ...item, state: 'saved', savedId: saved.id, error: undefined }
						: item
				);
			} catch (cause) {
				queue = queue.map((item) =>
					item.address === camera.address
						? { ...item, error: errorMessage(cause, 'Could not add this camera. Try again.') }
						: item
				);
			}
		}
		try {
			await getCameras().refresh();
		} finally {
			saving = false;
		}
		if (!queue.some((camera) => selected.includes(camera.address) && camera.state !== 'saved'))
			await ondone();
	}
</script>

<section class="flex flex-col gap-6" aria-label="Set up several cameras">
	<p class="text-sm text-muted-foreground">
		Select cameras that share a login. Check their pictures, name them, and add them together.
	</p>
	{#if choosing}
		<Button type="button" variant="outline" class="self-start" disabled={busy} onclick={onfind}
			>{finding ? 'Looking for cameras…' : 'Find cameras'}</Button
		>
		{#if discoveryMessage}<p role="status" class="text-sm text-muted-foreground">
				{discoveryMessage}
			</p>{/if}
		<Field.Set
			><Field.Legend>Available cameras</Field.Legend><Field.Group>
				{#each candidates as camera, index (camera.address)}
					<Field.Field orientation="horizontal">
						<Checkbox
							id={`discover-${index}`}
							checked={selected.includes(camera.address)}
							disabled={busy ||
								queue.some((item) => item.address === camera.address && item.state === 'saved')}
							onCheckedChange={(checked) => select(camera.address, checked)}
						/>
						<Field.Label for={`discover-${index}`} class="min-w-0 flex-col items-start"
							>{camera.name}<span class="text-xs font-normal break-all text-muted-foreground"
								>{camera.address}</span
							></Field.Label
						>
					</Field.Field>
				{/each}
			</Field.Group></Field.Set
		>
		<Field.Group class="max-w-xl sm:grid sm:grid-cols-2 sm:gap-4">
			<Field.Field
				><Field.Label for="batch-username">Camera username</Field.Label><Input
					id="batch-username"
					bind:value={username}
					disabled={busy}
					autocomplete="off"
				/></Field.Field
			>
			<Field.Field
				><Field.Label for="batch-password">Camera password</Field.Label><Input
					id="batch-password"
					type="password"
					bind:value={password}
					disabled={busy}
					autocomplete="off"
				/></Field.Field
			>
		</Field.Group>
		<Button type="button" class="self-start" disabled={busy || !selected.length} onclick={connect}
			>{failures ? 'Retry connections' : 'Preview selected cameras'}</Button
		>
	{/if}
	{#if queue.length}
		<div class="grid items-start gap-6 sm:grid-cols-2 xl:grid-cols-3">
			{#each queue as camera, index (camera.address)}
				<div class="flex min-w-0 flex-col gap-3">
					<CardOverlay>
						{#if camera.connection?.check}<img
								src={camera.connection.check.previewUrl}
								alt={`${camera.name} connection preview`}
								class="aspect-video w-full bg-muted object-contain"
							/>
						{:else}<div class="aspect-video w-full bg-muted"></div>{/if}
						{#snippet overlay()}<div class="flex flex-wrap gap-2">
								<Badge
									variant={camera.state === 'failed'
										? 'destructive'
										: camera.state === 'ready' || camera.state === 'saved'
											? 'success'
											: 'secondary'}
									role="status">{labels[camera.state]}</Badge
								>
							</div>{/snippet}
					</CardOverlay>
					<Field.Field orientation="horizontal">
						<Checkbox
							id={`include-${index}`}
							checked={selected.includes(camera.address)}
							disabled={busy || camera.state === 'saved'}
							onCheckedChange={(checked) => select(camera.address, checked)}
							aria-label={`Add ${camera.name}`}
						/>
						<Field.Label for={`name-${index}`} class="sr-only">Camera name</Field.Label>
						<Input
							id={`name-${index}`}
							bind:value={camera.name}
							disabled={busy || camera.state === 'saved'}
							placeholder="Camera name"
						/>
					</Field.Field>
					{#if camera.connection && camera.connection.profiles.length > 1}
						<Field.Field
							><Field.Label for={`profile-${index}`}>Camera channel or stream</Field.Label>
							<NativeSelect.Root
								id={`profile-${index}`}
								value={camera.connection.connection?.profileToken ?? ''}
								disabled={busy || camera.state === 'saved'}
								onchange={(event) => refreshPicture(camera, event.currentTarget.value)}
							>
								{#each camera.connection.profiles as profile (profile.token)}<NativeSelect.Option
										value={profile.token}>{profile.name}</NativeSelect.Option
									>{/each}
							</NativeSelect.Root>
						</Field.Field>
					{/if}

					{#if camera.error}<p role="alert" class="text-sm text-destructive">{camera.error}</p>{/if}
					{#if camera.error && camera.state === 'ready'}<Button
							type="button"
							variant="outline"
							class="self-start"
							disabled={busy}
							onclick={() => refreshPicture(camera)}>Refresh picture</Button
						>{/if}
				</div>
			{/each}
		</div>
		<div class="flex flex-wrap gap-3">
			<Button
				type="button"
				disabled={busy || !ready.length || ready.some((camera) => !camera.name.trim())}
				onclick={save}
				>{saving ? 'Adding cameras…' : `Add selected cameras (${ready.length})`}</Button
			>
			{#if !choosing}<Button
					type="button"
					variant="outline"
					disabled={busy}
					onclick={() => (choosing = true)}
					>{failures ? 'Change login or retry' : 'Select more cameras'}</Button
				>{/if}
			{#if queue.some((camera) => camera.state === 'saved')}<Button
					type="button"
					variant="outline"
					disabled={busy}
					onclick={ondone}>Done</Button
				>{/if}
		</div>
	{/if}
	<Button type="button" variant="outline" class="self-start" disabled={busy} onclick={onclose}
		>Single camera / manual entry</Button
	>
</section>

<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import DetectorRuntime from './detector-runtime.svelte';
	import { getRuntime, startDetector, stopDetector } from '$lib/remote/runtime.remote';
	import { resolve } from '$app/paths';
	import { CircleCheck, LoaderCircle } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import * as Card from '$lib/components/ui/card';
	import * as Alert from '$lib/components/ui/alert';
	import { errorMessage } from '$lib/remote-errors';
	import { getCameras } from '$lib/remote/stream.remote';
	import { getSetupStatus, finishSetup } from '$lib/remote/camera-setup.remote';

	let { configured }: { configured: boolean } = $props();
	const runtimeQuery = getRuntime();
	const initialRuntime = await runtimeQuery;
	const runtime = $derived(runtimeQuery.current ?? initialRuntime);
	let finishing = $state(false);
	let cameras = $state(await getSetupStatus());
	let saving = $state(false);
	let checkingId = $state('');
	let recordingErrors = $state<Record<string, string>>({});
	let message = $state('');
	let connectionLost = $state(false);
	let lastCheckedAt = $state(Date.now());
	let now = $state(Date.now());
	let controller: AbortController;
	const stale = $derived(connectionLost || now - lastCheckedAt > 10000);
	const busy = $derived(saving || Boolean(checkingId));
	const hasRecordings = $derived(cameras.some((camera) => camera.archiveDestinations > 0));
	const destination = $derived(hasRecordings ? '/detections' : '/streams');
	const finished = $derived(cameras.length > 0 && cameras.every((camera) => camera.completedAt));
	const ready = $derived(
		cameras.length > 0 &&
			cameras.every((camera) => camera.readyToFinish && (!camera.monitored || camera.monitoring))
	);
	const needsAlertChoice = $derived(
		cameras.some((camera) => camera.monitored && !camera.alerts.length)
	);

	async function refresh() {
		await getSetupStatus().refresh();
		cameras = await getSetupStatus();
		connectionLost = false;
		lastCheckedAt = Date.now();
	}

	async function checkRecordings(ids: string[]) {
		for (const id of ids) {
			if (controller.signal.aborted) return;
			checkingId = id;
			delete recordingErrors[id];
			try {
				const response = await fetch(resolve(`/cameras/${id}/archive-check`), {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: '{}',
					signal: controller.signal
				});
				if (response.status >= 500)
					throw new Error('The recording check could not finish. Try again.');
				const result = await response.json();
				if (!response.ok) throw new Error(result.message);
				await refresh();
			} catch (cause) {
				if (controller.signal.aborted) return;
				recordingErrors[id] = errorMessage(cause, 'The recording location could not be checked.');
			}
		}
		checkingId = '';
	}

	onMount(() => {
		controller = new AbortController();
		let timer: ReturnType<typeof setTimeout>;
		const clock = setInterval(() => (now = Date.now()), 2000);
		async function poll() {
			try {
				await refresh();
				if (controller.signal.aborted) return;
				if (finishing && !saving) {
					if (runtime.phase === 'failed') {
						finishing = false;
						message = runtime.message;
					} else if (ready) await save();
					else if (Object.keys(recordingErrors).length) finishing = false;
				}
				if (!busy)
					void checkRecordings(
						cameras
							.filter(
								(camera) =>
									camera.pictureVerifiedAt &&
									camera.archiveDestinations &&
									!camera.archiveVerifiedAt &&
									!recordingErrors[camera.id]
							)
							.map((camera) => camera.id)
					);
			} catch {
				connectionLost = true;
			}
			if (!controller.signal.aborted) timer = setTimeout(poll, 2000);
		}
		void poll();
		return () => {
			controller.abort();
			clearTimeout(timer);
			clearInterval(clock);
		};
	});

	async function save() {
		saving = true;
		message = '';
		try {
			await finishSetup().updates(getSetupStatus(), getCameras());
			cameras = await getSetupStatus();
			if (!controller.signal.aborted) await goto(resolve(destination));
		} catch (cause) {
			finishing = false;
			message = errorMessage(cause, 'Your progress could not be saved. Try again.');
		} finally {
			saving = false;
		}
	}
	async function start() {
		message = '';
		saving = true;
		try {
			if (
				configured &&
				runtime.managed &&
				!['running', 'starting', 'checking'].includes(runtime.phase)
			)
				await startDetector(runtime.mode).updates(runtimeQuery);
			finishing = true;
		} catch (cause) {
			message = errorMessage(cause, 'Could not start monitoring. Try again.');
		} finally {
			saving = false;
		}
	}
	async function cancel() {
		finishing = false;
		try {
			await stopDetector().updates(runtimeQuery);
		} catch (cause) {
			message = errorMessage(cause, 'Could not pause monitoring. Try again.');
		}
	}
</script>

<DetectorRuntime {configured} showControls={finished} />
<Card.Root>
	<Card.Header>
		<Card.Title>{finished ? 'Setup complete' : 'Check your cameras'}</Card.Title>
		<Card.Description
			>{finished
				? 'Your cameras and detectors are saved.'
				: hasRecordings
					? 'Recording locations are checked automatically. Your progress is saved as you go.'
					: 'Your progress is saved as you go.'}</Card.Description
		>
	</Card.Header>
	<Card.Content class="flex flex-col gap-5">
		{#if stale}<Alert.Root variant="destructive"
				><Alert.Title>Status unavailable</Alert.Title><Alert.Description
					>Connection to the app was lost. Reconnecting…</Alert.Description
				></Alert.Root
			>{/if}
		<ul class="flex flex-col gap-4">
			{#each cameras as camera (camera.id)}
				{@const checked =
					camera.pictureVerifiedAt && (!camera.archiveDestinations || camera.archiveVerifiedAt)}
				<li class="flex flex-col gap-2">
					<div class="flex flex-wrap items-center justify-between gap-2">
						<span class="font-medium">{camera.label}</span>
						{#if checked}<span class="flex items-center gap-1.5 text-sm text-muted-foreground"
								><CircleCheck class="size-4" aria-hidden="true" />Picture{camera.archiveDestinations
									? ' and recording checked'
									: ' checked'}</span
							>{/if}
					</div>
					{#if !camera.pictureVerifiedAt}
						<Button
							href={resolve(`/setup?step=cameras&camera=${camera.id}`)}
							variant="outline"
							size="sm"
							class="self-start">Confirm camera picture</Button
						>
					{:else if camera.archiveDestinations && !camera.archiveVerifiedAt}
						{#if recordingErrors[camera.id]}
							<p role="alert" class="text-sm text-destructive">{recordingErrors[camera.id]}</p>
							<Button
								type="button"
								variant="outline"
								size="sm"
								class="self-start"
								disabled={busy}
								onclick={() => checkRecordings([camera.id])}>Retry recording check</Button
							>
						{:else}<p role="status" class="flex items-center gap-2 text-sm text-muted-foreground">
								<LoaderCircle class="size-4 animate-spin" aria-hidden="true" />{checkingId ===
								camera.id
									? 'Checking recording location…'
									: 'Waiting to check recording location…'}
							</p>{/if}
					{/if}
					{#if !finished && camera.monitored && !camera.monitoring && !stale}<p
							class="text-sm text-muted-foreground"
						>
							Waiting for monitoring.
						</p>{/if}
				</li>
			{/each}
		</ul>
		{#if needsAlertChoice}
			<div class="flex flex-col gap-3 border-t pt-5">
				<p class="text-sm text-muted-foreground">
					Phone alerts are optional. You can connect them now or later from Alerts.
				</p>
				<div class="flex flex-wrap gap-2">
					<Button href={resolve('/notifications/add?setup=1')} variant="outline"
						>Connect phone alerts</Button
					>
				</div>
			</div>
		{/if}
		{#if message}<Alert.Root variant="destructive"
				><Alert.Title>Setup needs attention</Alert.Title><Alert.Description
					>{message}</Alert.Description
				></Alert.Root
			>{/if}
	</Card.Content>
	<Card.Footer>
		{#if finished}<Button href={resolve(destination)}
				>{hasRecordings ? 'Open recordings' : 'Open cameras'}</Button
			>
		{:else}<Button
				disabled={saving ||
					stale ||
					finishing ||
					cameras.some((camera) => !camera.pictureVerifiedAt)}
				onclick={start}
				>{saving || finishing
					? runtime.phase === 'starting' || runtime.phase === 'checking'
						? 'Starting monitoring…'
						: 'Checking setup…'
					: configured && runtime.managed && runtime.phase !== 'running'
						? 'Start monitoring'
						: hasRecordings
							? 'Finish and open recordings'
							: 'Finish and open cameras'}</Button
			>{/if}
		{#if !finished && runtime.managed && (finishing || ['running', 'checking'].includes(runtime.phase))}<Button
				class="ml-3"
				variant="outline"
				onclick={cancel}
				>{finishing || runtime.phase === 'checking' ? 'Cancel' : 'Pause monitoring'}</Button
			>{/if}
	</Card.Footer>
</Card.Root>

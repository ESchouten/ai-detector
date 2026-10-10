<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { Bell, BellOff, CircleCheck, CircleX, LoaderCircle, Play } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import * as Alert from '$lib/components/ui/alert';
	import { useRuntimeStatus } from '$lib/hooks/runtime-status.svelte';
	import { SetupVerifier } from '$lib/hooks/setup-verifier.svelte';
	import { errorMessage } from '$lib/remote-errors';
	import { getSetupStatus } from '$lib/remote/camera-setup.remote';
	import { startDetector, stopDetector } from '$lib/remote/runtime.remote';

	// The last step: check every camera, start monitoring, and leave once it is really running.
	let { configured }: { configured: boolean } = $props();
	const monitor = useRuntimeStatus();
	const initialRuntime = monitor.query.current ?? (await monitor.query);
	const runtime = $derived(monitor.query.current ?? initialRuntime);
	const verifier = new SetupVerifier(await getSetupStatus());
	const destination = $derived(configured ? resolve('/detections') : resolve('/streams'));
	let finishing = $state(false);
	let saving = $state(false);
	let message = $state('');
	const stale = $derived(verifier.connectionLost || monitor.stale);
	/** Without the desktop app, the detector is started elsewhere and cannot be verified here. */
	const external = $derived(configured && !runtime.managed);
	const starting = $derived(saving || finishing);
	const alerts = $derived([...new Set(verifier.cameras.flatMap((camera) => camera.alerts))]);
	const rows = $derived(
		verifier.cameras.map((camera) => ({
			camera,
			error: verifier.errors[camera.id],
			checked: !verifier.needsCheck(camera),
			// Checked, but monitoring has not analysed a picture from it yet.
			waiting: finishing && camera.monitored && !camera.monitoring
		}))
	);

	onMount(() =>
		verifier.start(async () => {
			if (!finishing || saving) return;
			if (runtime.phase === 'failed') {
				finishing = false;
				message = runtime.message;
			} else if (verifier.ready) await complete();
			else if (verifier.failed) finishing = false;
		})
	);

	async function complete() {
		saving = true;
		message = '';
		try {
			await verifier.finish();
			if (verifier.stopped) return;
			if (configured) await goto(resolve('/detections'));
			else await goto(resolve('/streams'));
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
				await startDetector().updates(monitor.query);
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
			await stopDetector().updates(monitor.query);
		} catch (cause) {
			message = errorMessage(cause, 'Could not pause monitoring. Try again.');
		}
	}
</script>

<div class="flex flex-col gap-6">
	{#if stale}
		<Alert.Root variant="destructive">
			<Alert.Title>Status unavailable</Alert.Title>
			<Alert.Description>Connection to the app was lost. Reconnecting…</Alert.Description>
		</Alert.Root>
	{/if}

	<ul class="panel divide-y">
		{#each rows as { camera, error, checked, waiting } (camera.id)}
			<li class="flex flex-col gap-2 px-4 py-3.5">
				<div class="flex items-start gap-3">
					<span class="mt-0.5 shrink-0">
						{#if error}<CircleX class="size-5 text-danger-foreground" aria-hidden="true" />
						{:else if checked && !waiting}<CircleCheck
								class="size-5 text-status-ok"
								aria-hidden="true"
							/>
						{:else}<LoaderCircle
								class="size-5 animate-spin text-muted-foreground"
								aria-hidden="true"
							/>{/if}
					</span>
					<div class="flex min-w-0 flex-1 flex-col gap-0.5">
						<p class="text-sm font-medium break-words">{camera.label}</p>
						<p
							class={[
								'text-sm break-words',
								error ? 'text-danger-foreground' : 'text-muted-foreground'
							]}
							role={error ? 'alert' : 'status'}
						>
							{#if error}{error}
							{:else if !checked}
								{verifier.checking === camera.id
									? camera.pictureVerifiedAt
										? 'Checking the recording location…'
										: 'Checking the picture…'
									: 'Waiting to be checked…'}
							{:else if waiting}
								Waiting for the first analysed picture…
							{:else if camera.monitored && camera.monitoring}
								Monitoring
							{:else}
								{camera.archiveDestinations
									? 'Picture and recording location checked'
									: 'Picture checked'}{#if !camera.monitored}
									· Live viewing only{/if}
							{/if}
						</p>
					</div>
					{#if error}
						<div class="flex shrink-0 flex-wrap justify-end gap-2">
							<Button
								variant="outline"
								size="sm"
								disabled={Boolean(verifier.checking)}
								onclick={() => verifier.retry(camera.id)}>Try again</Button
							>
							<Button
								variant="ghost"
								size="sm"
								href={resolve(`/streams/${encodeURIComponent(camera.id)}`)}>Open camera</Button
							>
						</div>
					{/if}
				</div>
			</li>
		{/each}
		{#if configured}
			<li class="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3.5">
				{#if alerts.length}
					<Bell class="size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
					<p class="min-w-0 flex-1 text-sm">Alerts go to {alerts.join(', ')}</p>
				{:else}
					<BellOff class="size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
					<p class="min-w-0 flex-1 basis-48 text-sm text-muted-foreground">
						No phone alerts. Recordings still appear in this app.
					</p>
					<Button
						variant="outline"
						size="sm"
						disabled={starting}
						href={resolve('/setup?step=detectors')}>Add phone alerts</Button
					>
				{/if}
			</li>
		{/if}
	</ul>

	{#if external}
		<p class="text-sm leading-relaxed text-muted-foreground">
			Detection runs separately from this app. Restart your detector so it uses these settings.
		</p>
	{/if}
	{#if finishing && !message}
		<p role="status" class="flex items-center gap-2 text-sm text-muted-foreground">
			<LoaderCircle class="size-4 shrink-0 animate-spin" aria-hidden="true" />
			{runtime.preparation ?? runtime.message}
		</p>
	{/if}
	{#if message}
		<Alert.Root variant="destructive">
			<Alert.Title>Setup needs attention</Alert.Title>
			<Alert.Description>{message}</Alert.Description>
		</Alert.Root>
	{/if}

	<div class="flex flex-wrap gap-3">
		{#if verifier.finished || external}
			<Button size="lg" href={destination}>{configured ? 'Open recordings' : 'Open cameras'}</Button
			>
		{:else}
			<Button
				size="lg"
				disabled={starting || stale || verifier.cameras.some((camera) => !camera.pictureVerifiedAt)}
				onclick={start}
			>
				{#if starting}<LoaderCircle
						data-icon="inline-start"
						class="animate-spin"
						aria-hidden="true"
					/>{:else if configured && runtime.phase !== 'running'}<Play
						data-icon="inline-start"
						aria-hidden="true"
					/>{/if}
				{starting
					? configured
						? 'Starting monitoring…'
						: 'Finishing…'
					: configured && runtime.phase !== 'running'
						? 'Start monitoring'
						: 'Finish setup'}
			</Button>
			{#if configured && runtime.managed && (finishing || ['running', 'checking'].includes(runtime.phase))}
				<Button size="lg" variant="outline" onclick={cancel}>
					{finishing || runtime.phase === 'checking' ? 'Cancel' : 'Pause monitoring'}
				</Button>
			{/if}
		{/if}
	</div>
</div>

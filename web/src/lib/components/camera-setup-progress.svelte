<script lang="ts">
	import { onDestroy, onMount, untrack } from 'svelte';
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
	import * as Card from '$lib/components/ui/card';
	import { errorMessage } from '$lib/remote-errors';
	import { getCameras } from '$lib/remote/stream.remote';
	import {
		getCameraSetup,
		skipCameraAlerts,
		finishCameraSetup
	} from '$lib/remote/camera-setup.remote';
	let { id, checkId }: { id: string; checkId?: string } = $props();
	let setup = $state(await getCameraSetup(untrack(() => id)));
	let busy = $state(false);
	let message = $state('');
	let connectionLost = $state(false);
	let lastCheckedAt = $state(Date.now());
	let now = $state(Date.now());
	const statusUnavailable = $derived(connectionLost || now - lastCheckedAt > 10000);
	let controller: AbortController | undefined;
	onDestroy(() => controller?.abort());
	async function refreshStatus() {
		await getCameraSetup(id).refresh();
		setup = await getCameraSetup(id);
		connectionLost = false;
		lastCheckedAt = Date.now();
	}
	onMount(() => {
		let active = true;
		let timer: ReturnType<typeof setTimeout>;
		const clock = setInterval(() => (now = Date.now()), 2000);
		if (checkId && setup.monitored && setup.archiveDestinations && !setup.archiveVerifiedAt)
			void checkArchive(checkId);
		async function refresh() {
			try {
				await refreshStatus();
			} catch {
				connectionLost = true;
			}
			if (active) timer = setTimeout(refresh, 2000);
		}
		timer = setTimeout(refresh, 2000);
		return () => {
			active = false;
			clearTimeout(timer);
			clearInterval(clock);
		};
	});
	async function action(choice: 'skip' | 'finish') {
		busy = true;
		message = '';
		try {
			await (choice === 'skip' ? skipCameraAlerts(id) : finishCameraSetup(id)).updates(
				getCameraSetup(id),
				getCameras()
			);
			setup = await getCameraSetup(id);
			connectionLost = false;
			lastCheckedAt = Date.now();
		} catch (cause) {
			message = errorMessage(cause, 'Your progress could not be saved. Try again.');
		} finally {
			busy = false;
		}
	}
	async function checkArchive(existingCheck?: string) {
		busy = true;
		message = '';
		const check = new AbortController();
		controller = check;
		try {
			const response = await fetch(resolve(`/cameras/${id}/archive-check`), {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ checkId: existingCheck }),
				signal: check.signal
			});
			if (response.status >= 500)
				throw new Error('The recording location check could not finish. Try again.');
			const result = await response.json();
			if (!response.ok) throw new Error(result.message);
			await refreshStatus();
		} catch (cause) {
			if (!check.signal.aborted)
				message = errorMessage(cause, 'The recording location could not be checked.');
		} finally {
			controller = undefined;
			busy = false;
		}
	}
</script>

<Card.Root>
	<Card.Header>
		<Card.Title
			>{setup.completedAt
				? `${setup.label}: setup finished`
				: `Finish setting up ${setup.label}`}</Card.Title
		>
		<Card.Description
			>Your progress is saved on this computer. You can come back and finish later.</Card.Description
		>
	</Card.Header>
	<Card.Content class="flex flex-col gap-5">
		<div class="flex flex-col gap-2">
			<p class="font-medium">
				1. Camera picture · {setup.pictureVerifiedAt ? 'Confirmed' : 'Needs confirmation'}
			</p>
			{#if setup.pictureVerifiedAt}<p class="text-sm text-muted-foreground">
					You confirmed this camera’s picture and test recording on {new Date(
						setup.pictureVerifiedAt
					).toLocaleString()}.
				</p>{/if}
			<Button href={resolve(`/streams/add?id=${id}`)} variant="outline"
				>{setup.pictureVerifiedAt ? 'Camera settings' : 'Confirm camera picture'}</Button
			>
		</div>
		<div class="flex flex-col gap-2">
			<p class="font-medium">
				2. Monitoring · {!setup.monitored
					? 'View only selected'
					: statusUnavailable
						? 'Status unavailable'
						: setup.monitoring
							? 'Verified now'
							: 'Not verified yet'}
			</p>
			<p class="text-sm text-muted-foreground">
				{setup.monitored
					? statusUnavailable
						? `Connection to the app was lost. Last checked ${new Date(lastCheckedAt).toLocaleTimeString()}. Reconnecting…`
						: setup.monitoringMessage
					: 'This camera is available for viewing. It will not create detections or send alerts.'}
			</p>
		</div>
		{#if setup.monitored}
			<div class="flex flex-col gap-2">
				<p class="font-medium">
					3. Recording location · {!setup.archiveDestinations
						? 'Not configured'
						: setup.archiveVerifiedAt
							? 'Checked'
							: 'Needs a check'}
				</p>
				{#if setup.archiveDestinations}
					<p class="text-sm text-muted-foreground">
						Save and reopen a short setup test in the configured recording location. The test is
						removed afterward and does not appear as a detection.
					</p>
					{#if setup.archiveVerifiedAt}<p class="text-sm text-muted-foreground">
							Checked {new Date(setup.archiveVerifiedAt).toLocaleString()}. Actual detection
							recordings are checked separately while monitoring runs.
						</p>{/if}
					<Button type="button" variant="outline" disabled={busy} onclick={() => checkArchive()}
						>{busy
							? 'Please wait…'
							: setup.archiveVerifiedAt
								? 'Check recording location again'
								: 'Check recording location'}</Button
					>
				{:else}<p class="text-sm text-muted-foreground">
						The current rules do not save local recordings.
					</p>{/if}
			</div>
			<div class="flex flex-col gap-2">
				<p class="font-medium">
					4. Alerts · {setup.alerts.length
						? 'Connected'
						: setup.alertsSkipped
							? 'Skipped for now'
							: 'Your choice'}
				</p>
				<p class="text-sm text-muted-foreground">
					{setup.alerts.length
						? `Connected to ${setup.alerts.join(', ')}.`
						: setup.alertsSkipped
							? 'No alerts are connected. You can add them later.'
							: 'Connect alerts, or choose to use recordings without alerts for now.'}
				</p>
				<div class="flex flex-wrap gap-2">
					<Button href={resolve(`/notifications/add?camera=${id}`)} variant="outline"
						>{setup.alerts.length ? 'Manage alerts' : 'Connect alerts'}</Button
					>
					{#if !setup.alerts.length && !setup.alertsSkipped}<Button
							type="button"
							variant="outline"
							disabled={busy}
							onclick={() => action('skip')}>No alerts for now</Button
						>{/if}
				</div>
			</div>
		{/if}
		{#if message}<p role="alert" class="text-sm text-destructive">{message}</p>{/if}
	</Card.Content>
	<Card.Footer class="flex flex-wrap gap-3">
		{#if !setup.completedAt}<Button
				type="button"
				disabled={busy ||
					statusUnavailable ||
					!setup.readyToFinish ||
					(setup.monitored && !setup.monitoring)}
				onclick={() => action('finish')}>Finish setup</Button
			>{/if}
		<Button href={resolve('/detections')} variant="outline"
			>{setup.completedAt ? 'Open recordings' : 'Continue later'}</Button
		>
	</Card.Footer>
</Card.Root>

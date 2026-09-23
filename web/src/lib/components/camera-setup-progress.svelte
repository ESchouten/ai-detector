<script lang="ts">
	import { onDestroy, onMount, untrack } from 'svelte';
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
	import { Badge } from '$lib/components/ui/badge';
	import { Separator } from '$lib/components/ui/separator';
	import * as Alert from '$lib/components/ui/alert';
	import { Activity, Bell, Camera, CircleCheck, FolderOpen, TriangleAlert } from '@lucide/svelte';
	import * as Card from '$lib/components/ui/card';
	import { errorMessage } from '$lib/remote-errors';
	import { getCameras } from '$lib/remote/stream.remote';
	import {
		getCameraSetup,
		skipCameraAlerts,
		finishCameraSetup
	} from '$lib/remote/camera-setup.remote';
	let {
		id,
		checkId,
		externalLinks = false
	}: { id: string; checkId?: string; externalLinks?: boolean } = $props();
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

{#snippet setupChecks()}
	<div class="flex flex-col gap-4">
		<div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
			<div class="flex min-w-0 gap-3">
				<Camera class="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
				<div class="flex min-w-0 flex-col gap-1.5">
					<div class="flex flex-wrap items-center gap-2">
						<h3 class="text-sm font-medium">Camera picture</h3>
						<Badge variant={setup.pictureVerifiedAt ? 'secondary' : 'outline'}>
							{#if setup.pictureVerifiedAt}<CircleCheck aria-hidden="true" />{/if}
							{setup.pictureVerifiedAt ? 'Confirmed' : 'Needs confirmation'}
						</Badge>
					</div>
					<p class="text-sm text-muted-foreground">
						{#if setup.pictureVerifiedAt}
							Picture and test recording confirmed on {new Date(
								setup.pictureVerifiedAt
							).toLocaleString()}.
						{:else}
							Check the camera view and play its short test recording.
						{/if}
					</p>
				</div>
			</div>
			<Button
				href={resolve(`/streams/add?id=${id}`)}
				variant="outline"
				size="sm"
				class="self-start"
				target={externalLinks ? '_blank' : undefined}
				rel="noopener"
			>
				{setup.pictureVerifiedAt ? 'Camera settings' : 'Confirm camera picture'}
			</Button>
		</div>
		<Separator />
		<div class="flex min-w-0 gap-3">
			<Activity class="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
			<div class="flex min-w-0 flex-col gap-1.5">
				<div class="flex flex-wrap items-center gap-2">
					<h3 class="text-sm font-medium">Monitoring</h3>
					<Badge
						variant={setup.monitored && statusUnavailable
							? 'destructive'
							: setup.monitoring
								? 'secondary'
								: 'outline'}
					>
						{#if setup.monitored && !statusUnavailable && setup.monitoring}<CircleCheck
								aria-hidden="true"
							/>{/if}
						{!setup.monitored
							? 'View only selected'
							: statusUnavailable
								? 'Status unavailable'
								: setup.monitoring
									? 'Verified now'
									: 'Not verified yet'}
					</Badge>
				</div>
				<p class="text-sm text-muted-foreground">
					{setup.monitored
						? statusUnavailable
							? `Connection to the app was lost. Last checked ${new Date(lastCheckedAt).toLocaleTimeString()}. Reconnecting…`
							: setup.monitoringMessage
						: 'This camera is available for viewing. It will not create detections or send alerts.'}
				</p>
			</div>
		</div>
		{#if setup.monitored}
			<Separator />
			<div class="flex min-w-0 gap-3">
				<FolderOpen class="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
				<div class="flex min-w-0 flex-1 flex-col gap-2">
					<div class="flex flex-wrap items-center gap-2">
						<h3 class="text-sm font-medium">Recording location</h3>
						<Badge
							variant={setup.archiveDestinations && setup.archiveVerifiedAt
								? 'secondary'
								: 'outline'}
						>
							{#if setup.archiveDestinations && setup.archiveVerifiedAt}<CircleCheck
									aria-hidden="true"
								/>{/if}
							{!setup.archiveDestinations
								? 'Not used by these settings'
								: setup.archiveVerifiedAt
									? 'Checked'
									: 'Needs a check'}
						</Badge>
					</div>
					{#if setup.archiveDestinations}
						<p class="text-sm text-muted-foreground">
							{#if setup.archiveVerifiedAt}
								Test recording saved and reopened on {new Date(
									setup.archiveVerifiedAt
								).toLocaleString()}. The test was removed. Actual detection recordings are checked
								separately while monitoring runs.
							{:else}
								Save and reopen a short test in the recording location. It is removed afterward and
								does not appear as a detection.
							{/if}
						</p>
						<Button
							type="button"
							variant="outline"
							size="sm"
							class="self-start"
							disabled={busy}
							onclick={() => checkArchive()}
						>
							{busy
								? 'Please wait…'
								: setup.archiveVerifiedAt
									? 'Check recording location again'
									: 'Check recording location'}
						</Button>
					{:else}
						<p class="text-sm text-muted-foreground">
							The current rules do not save local recordings.
						</p>
					{/if}
				</div>
			</div>
			<Separator />
			<div class="flex min-w-0 gap-3">
				<Bell class="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
				<div class="flex min-w-0 flex-1 flex-col gap-2">
					<div class="flex flex-wrap items-center gap-2">
						<h3 class="text-sm font-medium">Phone alerts</h3>
						<Badge variant={setup.alerts.length || setup.alertsSkipped ? 'secondary' : 'outline'}>
							{setup.alerts.length
								? 'Connected'
								: setup.alertsSkipped
									? 'Skipped for now'
									: 'Your choice'}
						</Badge>
					</div>
					<p class="text-sm text-muted-foreground">
						{setup.alerts.length
							? `Connected to ${setup.alerts.join(', ')}.`
							: setup.alertsSkipped
								? 'No alerts are connected. You can add them later.'
								: 'Connect alerts, or choose to use recordings without alerts for now.'}
					</p>
					<div class="flex flex-wrap gap-2">
						<Button
							href={resolve(`/notifications/add?camera=${id}`)}
							variant="outline"
							size="sm"
							target={externalLinks ? '_blank' : undefined}
							rel="noopener"
						>
							{setup.alerts.length ? 'Manage alerts' : 'Connect alerts'}
						</Button>
						{#if !setup.alerts.length && !setup.alertsSkipped}
							<Button
								type="button"
								variant="ghost"
								size="sm"
								disabled={busy}
								onclick={() => action('skip')}>No alerts for now</Button
							>
						{/if}
					</div>
				</div>
			</div>
		{/if}
	</div>
{/snippet}

<Card.Root>
	<Card.Header>
		<Card.Title>
			{setup.completedAt ? `${setup.label}: setup finished` : `Finish setting up ${setup.label}`}
		</Card.Title>
		<Card.Description>
			{setup.completedAt
				? 'Your camera is saved. Review its setup whenever you need.'
				: 'Your progress is saved on this computer. You can come back and finish later.'}
		</Card.Description>
	</Card.Header>
	<Card.Content class="flex flex-col gap-4">
		{#if setup.completedAt}
			<details>
				<summary class="cursor-pointer text-sm font-medium">Review setup checks</summary>
				<div class="mt-4">{@render setupChecks()}</div>
			</details>
		{:else}
			{@render setupChecks()}
		{/if}
		{#if message}
			<Alert.Root variant="destructive">
				<TriangleAlert aria-hidden="true" />
				<Alert.Title>Setup needs attention</Alert.Title>
				<Alert.Description>{message}</Alert.Description>
			</Alert.Root>
		{/if}
	</Card.Content>
	<Card.Footer class="flex flex-wrap gap-2">
		{#if !setup.completedAt}
			<Button
				type="button"
				disabled={busy ||
					statusUnavailable ||
					!setup.readyToFinish ||
					(setup.monitored && !setup.monitoring)}
				onclick={() => action('finish')}>Finish setup</Button
			>
		{/if}
		<Button
			href={resolve('/detections')}
			variant="outline"
			target={externalLinks ? '_blank' : undefined}
			rel="noopener"
		>
			{setup.completedAt ? 'Open recordings' : 'Continue later'}
		</Button>
	</Card.Footer>
</Card.Root>

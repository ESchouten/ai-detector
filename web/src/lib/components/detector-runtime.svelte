<script lang="ts">
	import { errorMessage } from '$lib/remote-errors';
	import { untrack } from 'svelte';
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
	import { Badge } from '$lib/components/ui/badge';
	import { Separator } from '$lib/components/ui/separator';
	import * as Alert from '$lib/components/ui/alert';
	import { CircleCheck, LoaderCircle, Pause, Play, TriangleAlert, Video, X } from '@lucide/svelte';
	import * as Card from '$lib/components/ui/card';
	import * as Field from '$lib/components/ui/field';
	import * as NativeSelect from '$lib/components/ui/native-select';
	import { startDetector, stopDetector } from '$lib/remote/runtime.remote';
	import { useRuntimeStatus } from '$lib/hooks/runtime-status.svelte';
	import type { RuntimeMode } from '$lib/runtime';
	let { configured, compact = false }: { configured: boolean; compact?: boolean } = $props();
	const monitor = useRuntimeStatus();
	// Query.current is client-only; the awaited value also supports server rendering.
	const initial = monitor.query.current ?? (await monitor.query);
	const runtime = $derived(monitor.query.current ?? initial);
	let mode = $state<RuntimeMode>(untrack(() => runtime.mode));
	let requestError = $state('');
	const stale = $derived(monitor.stale);
	let controlling = $state(false);
	const busy = $derived(
		controlling || ['checking', 'starting', 'stopping'].includes(runtime.phase)
	);
	const labels = {
		idle: 'Paused',
		preparing: 'Preparing',
		connecting: 'Connecting cameras',
		monitoring: 'Monitoring',
		degraded: 'Needs attention',
		failed: 'Needs attention'
	};
	const needsAttention = $derived(
		stale || !runtime.managed || ['failed', 'degraded'].includes(runtime.readiness)
	);
	let troubleshootingOpen = $state(untrack(() => needsAttention));
	const preparing = $derived(busy || ['preparing', 'connecting'].includes(runtime.readiness));
	const monitoringCount = $derived(
		runtime.cameras.filter(
			(camera) => camera.state === 'monitoring' && !camera.error && !camera.recordingError
		).length
	);
	const statusLabel = $derived(
		needsAttention
			? stale || !runtime.managed
				? 'Status unavailable'
				: 'Needs attention'
			: !configured
				? 'Live viewing only'
				: runtime.readiness === 'monitoring' && monitoringCount
					? `Monitoring ${monitoringCount} ${monitoringCount === 1 ? 'camera' : 'cameras'}`
					: labels[runtime.readiness]
	);

	const cameraLabels = {
		monitoring: 'Monitoring',
		paused: 'Paused',
		receiving: 'Preparing detection',
		connecting: 'Connecting',
		offline: 'Needs attention',
		failed: 'Needs attention'
	};
	async function control(action: 'start' | 'stop') {
		requestError = '';
		controlling = true;
		try {
			await (action === 'start' ? startDetector(mode) : stopDetector()).updates(monitor.query);
		} catch (cause) {
			requestError = errorMessage(
				cause,
				'The request could not be completed. Check that AI Detector is still open.'
			);
		} finally {
			controlling = false;
		}
	}
</script>

{#snippet controls()}
	{#if runtime.managed && configured}
		{#if runtime.phase === 'running'}
			<Button
				size={compact ? 'sm' : 'default'}
				variant="outline"
				aria-label="Pause monitoring"
				disabled={stale || controlling}
				onclick={() => control('stop')}
				><Pause data-icon="inline-start" aria-hidden="true" />{compact
					? 'Pause'
					: 'Pause monitoring'}</Button
			>
		{:else if runtime.phase === 'checking'}
			<Button
				size={compact ? 'sm' : 'default'}
				variant="outline"
				aria-label="Cancel preparation"
				disabled={stale || controlling}
				onclick={() => control('stop')}
				><X data-icon="inline-start" aria-hidden="true" />{compact
					? 'Cancel'
					: 'Cancel preparation'}</Button
			>
		{:else}
			<Button
				size={compact ? 'sm' : 'default'}
				aria-label={busy
					? 'Please wait…'
					: runtime.phase === 'failed'
						? 'Try again'
						: 'Start monitoring'}
				disabled={busy || stale}
				onclick={() => control('start')}
			>
				{#if busy}<LoaderCircle
						data-icon="inline-start"
						class="animate-spin"
						aria-hidden="true"
					/>{:else}<Play data-icon="inline-start" aria-hidden="true" />{/if}
				{busy
					? 'Please wait…'
					: runtime.phase === 'failed'
						? 'Try again'
						: compact
							? 'Start'
							: 'Start monitoring'}
			</Button>
		{/if}
	{:else if !configured}
		<Button href={resolve('/setup?step=detectors')} variant="outline" size="sm"
			>Choose a detector</Button
		>
	{/if}
{/snippet}

<Card.Root class={compact ? 'gap-3 border-0 bg-transparent py-0 shadow-none' : ''}>
	<Card.Header class={compact ? 'items-center px-0' : ''}>
		<Card.Title>
			<span class="flex items-center gap-2" role="status">
				{#if needsAttention}<TriangleAlert
						class="size-4 shrink-0 text-destructive"
						aria-hidden="true"
					/>
				{:else if runtime.readiness === 'monitoring'}<CircleCheck
						class="size-4 shrink-0"
						aria-hidden="true"
					/>
				{:else if preparing}<LoaderCircle
						class="size-4 shrink-0 animate-spin"
						aria-hidden="true"
					/>{/if}
				{statusLabel}
			</span>
		</Card.Title>
		{#if compact}<Card.Action>{@render controls()}</Card.Action>{/if}
		{#if needsAttention || preparing || (!compact && runtime.readiness !== 'monitoring')}
			<Card.Description aria-live="polite">
				{stale
					? `No recent status from the app. Last checked ${new Date(monitor.lastCheckedAt).toLocaleTimeString()}. Reopen AI Detector if it does not reconnect.`
					: (runtime.preparation ?? runtime.message)}
			</Card.Description>
		{/if}
	</Card.Header>
	{#if !compact || runtime.notice || requestError || needsAttention}
		<Card.Content class={compact ? 'flex flex-col gap-3 px-0' : 'flex flex-col gap-4'}>
			{#if runtime.notice}<p class="text-sm text-muted-foreground">{runtime.notice}</p>{/if}
			{#if requestError}
				<Alert.Root variant="destructive">
					<Alert.Title>Monitoring request failed</Alert.Title>
					<Alert.Description>{requestError}</Alert.Description>
				</Alert.Root>
			{/if}
			{#if compact && needsAttention}
				<Button href={resolve('/setup?step=finish')} variant="outline" size="sm" class="self-start"
					>View monitoring details</Button
				>
			{/if}
			{#if !compact}
				<p class="text-sm text-muted-foreground">
					Monitoring continues when you close this browser tab.
				</p>

				<details bind:open={troubleshootingOpen}>
					<summary class="cursor-pointer text-sm text-muted-foreground"
						>Advanced and troubleshooting</summary
					>
					<div class="mt-4 flex flex-col gap-4">
						{#if runtime.cameras.length && runtime.readiness !== 'idle'}
							<div class="flex flex-col gap-3">
								{#each runtime.cameras as camera, index (camera.id)}
									{#if index > 0}<Separator />{/if}
									<div class="flex min-w-0 items-start gap-3">
										<Video
											class="mt-0.5 size-5 shrink-0 text-muted-foreground"
											aria-hidden="true"
										/>
										<div class="flex min-w-0 flex-1 flex-col gap-1.5">
											<div class="flex flex-wrap items-center justify-between gap-2">
												<p class="min-w-0 text-sm font-medium break-words">{camera.label}</p>
												<Badge
													variant={stale ||
													camera.error ||
													camera.recordingError ||
													['offline', 'failed'].includes(camera.state)
														? 'destructive'
														: camera.state === 'monitoring'
															? 'secondary'
															: 'outline'}
												>
													{stale
														? 'Status unavailable'
														: camera.error || camera.recordingError
															? 'Needs attention'
															: cameraLabels[camera.state]}
												</Badge>
											</div>
											{#if camera.state === 'receiving' && !stale && !camera.error}
												<p class="text-sm text-muted-foreground">
													Picture received; waiting for detection.
												</p>
											{/if}
											{#if camera.error}<p class="text-sm break-words text-destructive">
													{camera.error}
												</p>{/if}
											{#if camera.recordingError}<p class="text-sm break-words text-destructive">
													Recording: {camera.recordingError}
												</p>{/if}
											{#if camera.lastFrameAt}<p class="text-xs text-muted-foreground">
													Last picture: {new Date(camera.lastFrameAt).toLocaleTimeString()}
												</p>{/if}
										</div>
									</div>
								{/each}
							</div>
						{/if}
						{#if runtime.managed}
							<Field.Group>
								<Field.Field>
									<Field.Label for="runtime-mode">Detection engine</Field.Label>
									<NativeSelect.Root
										id="runtime-mode"
										bind:value={mode}
										disabled={busy || runtime.phase === 'running'}
									>
										<NativeSelect.Option value="auto"
											>Automatically choose a working engine</NativeSelect.Option
										>
										<NativeSelect.Option value="native">Bundled application</NativeSelect.Option>
										<NativeSelect.Option value="docker"
											>Managed NVIDIA container</NativeSelect.Option
										>
									</NativeSelect.Root>
								</Field.Field>
							</Field.Group>
						{/if}
						{#if runtime.helpUrl}<Button
								href={runtime.helpUrl}
								target="_blank"
								rel="noreferrer"
								variant="outline"
								size="sm"
								class="self-start">Setup instructions</Button
							>{/if}
						<p class="text-xs break-all text-muted-foreground">
							Settings and recordings: {runtime.dataDirectory}
						</p>
						<pre
							class="max-h-64 overflow-auto rounded-md bg-muted p-3 text-xs break-all whitespace-pre-wrap">{runtime.logs ||
								'No diagnostic output yet.'}</pre>
					</div>
				</details>
			{/if}
		</Card.Content>
	{/if}
	{#if !compact}<Card.Footer>{@render controls()}</Card.Footer>{/if}
</Card.Root>

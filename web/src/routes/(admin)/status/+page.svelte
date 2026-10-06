<script lang="ts">
	import { resolve } from '$app/paths';
	import { ChevronDown, Download, ExternalLink, ScrollText } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import * as Collapsible from '$lib/components/ui/collapsible';
	import HeartbeatSettings from '$lib/components/heartbeat-settings.svelte';
	import MonitoringControl from '$lib/components/monitoring-control.svelte';
	import PageHeader from '$lib/components/page-header.svelte';
	import Pill from '$lib/components/pill.svelte';
	import StatusDot from '$lib/components/status-dot.svelte';
	import { cameraStatusBadge } from '$lib/camera-status';
	import { clockTime } from '$lib/format';
	import { useRuntimeStatus } from '$lib/hooks/runtime-status.svelte';
	import { monitoringSummary } from '$lib/monitoring';
	import { getDetectors } from '$lib/remote/detector.remote';

	const monitor = useRuntimeStatus();
	const initial = monitor.query.current ?? (await monitor.query);
	const runtime = $derived(monitor.query.current ?? initial);
	const detectors = $derived(await getDetectors());
	const stale = $derived(monitor.stale);
	const summary = $derived(monitoringSummary(runtime, { stale, configured: detectors.length > 0 }));
	const notes = $derived(
		[runtime.storageWarning, ...(runtime.issues ?? [])].filter((note): note is string => !!note)
	);
	const showCameras = $derived(runtime.cameras.length > 0 && runtime.readiness !== 'idle');
	// The page is named "Monitoring", and a camera "is monitoring": two words in other languages.
	// @wc-context: page name
	const pageName = 'Monitoring';
</script>

<svelte:head><title>Monitoring · AI Detector</title></svelte:head>

<section class="page-narrow">
	<PageHeader
		title={pageName}
		description="Whether your cameras are being watched right now, and what needs attention if they are not."
	/>

	<div class="panel flex flex-col gap-5 p-5">
		<div class="flex flex-wrap items-center gap-x-6 gap-y-4">
			<div class="flex min-w-0 flex-1 basis-64 items-start gap-3.5">
				<span class="mt-1.5"><StatusDot tone={summary.tone} class="size-3" /></span>
				<div class="flex min-w-0 flex-col gap-1">
					<p class="text-lg leading-tight font-semibold" role="status">{summary.label}</p>
					<p class="text-sm break-words text-muted-foreground" aria-live="polite">
						{summary.detail}
					</p>
				</div>
			</div>
			<MonitoringControl action={summary.action} />
			{#if !detectors.length}
				<Button href={resolve('/detectors/add')}>Add a detector</Button>
			{/if}
		</div>
		{#if stale}
			<p class="text-sm text-muted-foreground">
				Last heard from the app at {clockTime(monitor.lastCheckedAt)}.
			</p>
		{/if}
		{#if runtime.notice}<p class="text-sm text-muted-foreground">{runtime.notice}</p>{/if}
		{#if notes.length}
			<ul class="flex flex-col gap-2 border-t pt-4">
				{#each notes as note, index (index)}
					<li role="status" class="text-sm break-words text-danger-foreground">{note}</li>
				{/each}
			</ul>
		{/if}
	</div>

	{#if showCameras}
		<section class="flex flex-col gap-3" aria-labelledby="status-cameras">
			<h2 id="status-cameras" class="text-base font-semibold">Cameras</h2>
			<ul class="panel divide-y">
				{#each runtime.cameras as camera (camera.id)}
					{@const badge = cameraStatusBadge(camera, runtime, stale)}
					<li class="flex flex-col gap-1.5 px-4 py-3.5">
						<div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5">
							<p class="min-w-0 text-sm font-medium break-words">{camera.label}</p>
							<Pill tone={badge.tone}>{badge.label}</Pill>
						</div>
						{#if camera.state === 'receiving' && !stale && !camera.error}
							<p class="text-sm text-muted-foreground">Picture received; waiting for detection.</p>
						{/if}
						{#if camera.error}
							<p class="text-sm break-words text-danger-foreground">{camera.error}</p>
						{/if}
						{#if camera.recordingError}
							<p class="text-sm break-words text-danger-foreground">
								Recording: {camera.recordingError}
							</p>
						{/if}
						{#if camera.lastFrameAt}
							<p class="text-xs text-muted-foreground tabular-nums">
								Last picture {clockTime(camera.lastFrameAt)}
							</p>
						{/if}
					</li>
				{/each}
			</ul>
		</section>
	{/if}

	<HeartbeatSettings managed={runtime.managed} />

	<p class="text-sm leading-relaxed text-muted-foreground">
		Monitoring keeps running when you close this page. If AI Detector opens when you log in, it
		resumes by itself — unless you paused it here.
	</p>

	<Collapsible.Root class="panel">
		<Collapsible.Trigger
			class="group flex w-full items-center justify-between gap-3 rounded-xl px-4 py-3.5 text-left text-sm font-medium outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
		>
			<span class="flex flex-col">
				Technical details
				<span class="text-xs font-normal text-muted-foreground">For troubleshooting</span>
			</span>
			<ChevronDown
				class="size-4 shrink-0 text-muted-foreground transition-transform group-data-[state=open]:rotate-180"
				aria-hidden="true"
			/>
		</Collapsible.Trigger>
		<Collapsible.Content>
			<dl class="flex flex-col gap-3 border-t px-4 py-4 text-sm">
				{#each runtime.backends ?? [] as backend, index (index)}
					<div class="flex flex-wrap justify-between gap-x-4 gap-y-0.5">
						<dt class="text-muted-foreground">{backend.label} runs on</dt>
						<dd class="font-medium break-all">{backend.engine}</dd>
					</div>
				{/each}
				{#if !runtime.managed}
					<p class="text-muted-foreground">{runtime.message}</p>
				{/if}
				<div class="flex flex-col gap-0.5">
					<dt class="text-muted-foreground">Settings and recordings folder</dt>
					<dd class="font-mono text-xs break-all">{runtime.dataDirectory}</dd>
				</div>
			</dl>
			<div class="flex flex-wrap gap-2 border-t px-4 py-3.5">
				<Button href={resolve('/logs')} variant="outline" size="sm">
					<ScrollText data-icon="inline-start" aria-hidden="true" />View logs
				</Button>
				<Button
					href={resolve('/logs/diagnostics')}
					download="AI-Detector-diagnostics.zip"
					variant="outline"
					size="sm"
				>
					<Download data-icon="inline-start" aria-hidden="true" />Download diagnostics
				</Button>
				{#if runtime.helpUrl}
					<Button
						href={runtime.helpUrl}
						target="_blank"
						rel="noreferrer"
						variant="outline"
						size="sm"
					>
						Setup instructions<ExternalLink data-icon="inline-end" aria-hidden="true" />
					</Button>
				{/if}
			</div>
		</Collapsible.Content>
	</Collapsible.Root>
</section>

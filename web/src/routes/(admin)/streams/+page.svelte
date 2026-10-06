<script lang="ts">
	import { resolve } from '$app/paths';
	import { Cctv, Plus } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import * as Empty from '$lib/components/ui/empty';
	import * as Alert from '$lib/components/ui/alert';
	import CameraPicture from '$lib/components/camera-picture.svelte';
	import FilterChips from '$lib/components/filter-chips.svelte';
	import MonitoringBanner from '$lib/components/monitoring-banner.svelte';
	import PageHeader from '$lib/components/page-header.svelte';
	import Pill from '$lib/components/pill.svelte';
	import StatusDot from '$lib/components/status-dot.svelte';
	import { cameraStatusBadge } from '$lib/camera-status';
	import { getCameras } from '$lib/remote/camera.remote';
	import { getDetectorPresets } from '$lib/remote/detector.remote';
	import { useRuntimeStatus } from '$lib/hooks/runtime-status.svelte';
	import CameraHistory from './camera-history.svelte';
	const cameras = $derived(await getCameras());
	const { presets, warning: presetWarning } = await getDetectorPresets();
	const monitor = useRuntimeStatus();
	const initial = monitor.query.current ?? (await monitor.query);
	const runtime = $derived(monitor.query.current ?? initial);
	const stale = $derived(monitor.stale);
	const dots = { ok: 'ok', warn: 'warn', bad: 'bad', neutral: 'idle' } as const;
	let view = $state<'live' | 'history'>('live');
</script>

<svelte:head><title>Cameras · AI Detector</title></svelte:head>
<section class="page">
	<PageHeader title="Cameras">
		{#snippet actions()}
			{#if cameras.length}
				<Button href={resolve('/streams/add')}>
					<Plus data-icon="inline-start" aria-hidden="true" />Add camera
				</Button>
			{/if}
		{/snippet}
	</PageHeader>
	<MonitoringBanner configured={cameras.some((camera) => camera.monitored)} />
	{#if presetWarning}
		<Alert.Root variant="destructive">
			<Alert.Title>Monitoring preset names are unavailable</Alert.Title>
			<Alert.Description>
				{presetWarning} Cameras below show their saved detector names. Their settings are unchanged.
			</Alert.Description>
		</Alert.Root>
	{/if}
	{#if cameras.length}
		<FilterChips
			label="View"
			required
			value={view}
			options={[
				{ value: 'live', label: 'Live' },
				{ value: 'history', label: 'History' }
			]}
			onchange={(value) => (view = value ?? 'live')}
		/>
	{/if}
	{#if cameras.length && view === 'history'}
		<CameraHistory />
	{:else if cameras.length}
		<ul class="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
			{#each cameras as camera (camera.id)}
				{@const status = runtime.cameras.find((item) => item.id === camera.id)}
				{@const badge = camera.monitored
					? cameraStatusBadge(status, runtime, stale)
					: { label: 'Live view only', tone: 'neutral' as const }}
				<li class="flex min-w-0 flex-col gap-2">
					<div class="group relative">
						<CameraPicture id={camera.id} label={camera.label} monitored={camera.monitored}>
							{#snippet caption()}
								<div
									class="flex w-full min-w-0 flex-wrap items-end justify-between gap-x-3 gap-y-1.5"
								>
									<div class="flex min-w-0 items-center gap-2">
										<StatusDot tone={dots[badge.tone]} />
										<p class="min-w-0 truncate text-sm font-semibold">{camera.label}</p>
										{#if badge.tone !== 'ok'}
											<p class="shrink-0 text-xs text-media-foreground/75">{badge.label}</p>
										{:else}<span class="sr-only">{badge.label}</span>{/if}
									</div>
									<div class="flex flex-wrap justify-end gap-1.5">
										{#each camera.rules as rule (rule.label)}
											<Pill tone="category" seed={rule.preset ?? rule.label}>
												{presets.find((preset) => preset.id === rule.preset)?.name ?? rule.label}
											</Pill>
										{/each}
									</div>
								</div>
							{/snippet}
						</CameraPicture>
						<a
							href={resolve(`/streams/${encodeURIComponent(camera.id)}`)}
							class="absolute inset-0 z-10 rounded-xl outline-none focus-visible:ring-[3px] focus-visible:ring-ring/70"
							aria-label={`Open ${camera.label}`}
						></a>
					</div>
					{#if status?.error}
						<p role="alert" class="text-sm break-words text-danger-foreground">{status.error}</p>
					{/if}
					{#if status?.recordingError}
						<p role="alert" class="text-sm break-words text-danger-foreground">
							Recording: {status.recordingError}
						</p>
					{/if}
				</li>
			{/each}
		</ul>
	{:else}
		<Empty.Root class="border border-dashed">
			<Empty.Header>
				<Empty.Media variant="icon"><Cctv aria-hidden="true" /></Empty.Media>
				<Empty.Title>No cameras yet</Empty.Title>
				<Empty.Description>
					Connect a camera to see its live picture and choose what to detect.
				</Empty.Description>
			</Empty.Header>
			<Empty.Content>
				<Button href={resolve('/streams/add')}>Add your first camera</Button>
			</Empty.Content>
		</Empty.Root>
	{/if}
</section>

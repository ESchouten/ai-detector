<script lang="ts">
	import { resolve } from '$app/paths';
	import { Bell, BellOff, ChevronRight, Plus, ScanSearch, Sparkles } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import * as Empty from '$lib/components/ui/empty';
	import CategoryDot from '$lib/components/category-dot.svelte';
	import MonitoringBanner from '$lib/components/monitoring-banner.svelte';
	import PageHeader from '$lib/components/page-header.svelte';
	import { sameTelegram } from '$lib/configuration';
	import { plural } from '$lib/format';
	import { getDetectors, getDetectorPresets } from '$lib/remote/detector.remote';
	import { getTelegrams } from '$lib/remote/alerts.remote';
	import { getCameras } from '$lib/remote/camera.remote';

	const [detectors, cameras, telegrams, { presets }] = $derived(
		await Promise.all([getDetectors(), getCameras(), getTelegrams(), getDetectorPresets()])
	);
	const unwatched = $derived(cameras.filter((camera) => !camera.monitored));
</script>

<svelte:head><title>Detectors · AI Detector</title></svelte:head>
<section class="page-narrow">
	<PageHeader
		title="Detectors"
		description="A detector watches the cameras you choose, records what it sees and alerts the people you pick."
	>
		{#snippet actions()}
			{#if detectors.length}
				<Button href={resolve('/detectors/add')}>
					<Plus data-icon="inline-start" aria-hidden="true" />Add detector
				</Button>
			{/if}
		{/snippet}
	</PageHeader>
	<MonitoringBanner configured={detectors.length > 0} />

	{#if detectors.length}
		<ul class="flex flex-col gap-3">
			{#each detectors as { detector, meta } (meta.label)}
				{@const watched = detector.detection.source.map(
					(source) => cameras.find((camera) => camera.source === source)?.label ?? 'Custom source'
				)}
				{@const recipients = telegrams.filter((channel) =>
					detector.exporters?.telegram?.some((item) => sameTelegram(item, channel))
				)}
				{@const presetName = presets.find((preset) => preset.id === meta.preset)?.name}
				{@const validated = detector.vlm?.some((step) => step.key != null)}
				<li>
					<a
						href={resolve(`/detectors/edit?label=${encodeURIComponent(meta.label)}`)}
						aria-label={`Edit ${meta.label}`}
						class="panel group flex items-center gap-4 px-5 py-4 transition-colors outline-none hover:bg-accent/60 focus-visible:ring-[3px] focus-visible:ring-ring/50"
					>
						<div class="flex min-w-0 flex-1 flex-col gap-2">
							<div class="flex flex-wrap items-center gap-x-2.5 gap-y-1">
								<CategoryDot seed={meta.preset ?? meta.label} />
								<h2 class="text-base font-semibold">{meta.label}</h2>
								{#if presetName && presetName !== meta.label}
									<span class="text-sm text-muted-foreground">{presetName}</span>
								{/if}
							</div>
							<p class="text-sm text-muted-foreground">
								{plural(watched.length, ['# camera', '# cameras'])} · {watched.join(', ')}
							</p>
							<div class="flex flex-wrap gap-x-5 gap-y-1.5 text-sm">
								<span class="flex items-center gap-1.5">
									{#if recipients.length}
										<Bell class="size-4 text-muted-foreground" aria-hidden="true" />
										Alerts to {recipients.map(({ label }) => label).join(', ')}
									{:else}
										<BellOff class="size-4 text-muted-foreground" aria-hidden="true" />
										<span class="text-muted-foreground">No phone alerts</span>
									{/if}
								</span>
								{#if validated}
									<span class="flex items-center gap-1.5">
										<Sparkles class="size-4 text-muted-foreground" aria-hidden="true" />
										{meta.llmConnection
											? `Checked by ${meta.llmConnection}`
											: 'Checked by a custom validator'}
									</span>
								{/if}
							</div>
						</div>
						<ChevronRight
							class="size-5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5"
							aria-hidden="true"
						/>
					</a>
				</li>
			{/each}
		</ul>
		{#if unwatched.length}
			<p class="text-sm text-muted-foreground">
				{unwatched.length === 1
					? `${unwatched[0].label} is not watched by a detector, so it is for live viewing only.`
					: `${unwatched.map((camera) => camera.label).join(', ')} are not watched by a detector, so they are for live viewing only.`}
			</p>
		{/if}
	{:else}
		<Empty.Root class="border border-dashed">
			<Empty.Header>
				<Empty.Media variant="icon"><ScanSearch aria-hidden="true" /></Empty.Media>
				<Empty.Title>No detectors yet</Empty.Title>
				<Empty.Description>
					{cameras.length
						? 'Your cameras show a live picture. Add a detector to record events and get alerts.'
						: 'Connect a camera first, then choose what to detect on it.'}
				</Empty.Description>
			</Empty.Header>
			<Empty.Content>
				{#if cameras.length}
					<Button href={resolve('/detectors/add')}>Add a detector</Button>
				{:else}
					<Button href={resolve('/streams/add')}>Add a camera</Button>
				{/if}
			</Empty.Content>
		</Empty.Root>
	{/if}
</section>

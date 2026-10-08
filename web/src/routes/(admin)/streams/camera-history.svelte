<script lang="ts">
	import { onMount } from 'svelte';
	import { badgeHue } from '$lib/badge-colors';
	import { axisTicks, watchedTime, type WatchState } from '$lib/camera-history';
	import FilterChips from '$lib/components/filter-chips.svelte';
	import { detectionKey, type Detection } from '$lib/detections';
	import { percent, timeOfDay, weekday } from '$lib/format';
	import { getCameraHistory } from '$lib/remote/camera.remote';
	import { getRecordingPresets } from '$lib/remote/detections.remote';
	import RecordingViewer from '../detections/recording-viewer.svelte';

	// When each camera was really watched, with what it recorded on the same line: a gap in the
	// green is time nothing would have been noticed.
	let hours = $state<1 | 24 | 168>(24);
	const colorSeeds = await getRecordingPresets();
	const history = $derived(await getCameraHistory(hours));
	onMount(() => {
		const timer = setInterval(() => void getCameraHistory(hours).refresh(), 60000);
		return () => clearInterval(timer);
	});

	const from = $derived(Date.parse(history.from));
	const span = $derived(Date.parse(history.to) - from);
	const place = (moment: string) => ((Date.parse(moment) - from) / span) * 100;
	const rows = $derived([
		...history.cameras,
		...(history.others.length
			? [{ id: '', label: 'Other recordings', stretches: [], detections: history.others }]
			: [])
	]);

	// Reviews and deletions made in the viewer show at once; the next refresh confirms them.
	let reviewed = $state<Record<string, Detection>>({});
	let removed = $state<string[]>([]);
	const shown = (detections: Detection[]) =>
		detections
			.filter((detection) => !removed.includes(detectionKey(detection)))
			.map((detection) => reviewed[detectionKey(detection)] ?? detection);
	const entries = $derived(
		shown(rows.flatMap((row) => row.detections)).sort((a, b) =>
			b.timestamp.localeCompare(a.timestamp)
		)
	);
	let selected = $state<string | null>(null);

	/** Every ten minutes over an hour, three hours over a day, midnights over a week. */
	const ticks = $derived(
		axisTicks(from, from + span, { 1: 10, 24: 180, 168: 1440 }[hours] * 60000).map((tick) => ({
			at: ((tick - from) / span) * 100,
			label: hours === 168 ? weekday(tick) : timeOfDay(tick)
		}))
	);

	const states: Record<WatchState, { label: string; class: string }> = {
		watched: { label: 'Watched', class: 'bg-status-ok/35' },
		connecting: { label: 'Connecting', class: 'bg-status-warn/45' },
		offline: { label: 'Camera offline', class: 'bg-status-bad/55' },
		paused: { label: 'Paused', class: 'history-hatched text-muted-foreground/45' },
		stopped: { label: 'AI Detector was not running', class: 'history-hatched text-status-bad/60' }
	};
	function duration(milliseconds: number): string {
		const minutes = Math.round(milliseconds / 60000);
		return minutes < 60
			? `${minutes} min`
			: `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, '0')} min`;
	}
	const moment = (value: string) =>
		hours === 168 ? `${weekday(value)} ${timeOfDay(value)}` : timeOfDay(value);
</script>

<div class="flex flex-col gap-5">
	<div class="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
		<FilterChips
			label="Period"
			required
			value={String(hours)}
			options={[
				{ value: '1', label: 'Last hour' },
				{ value: '24', label: 'Last 24 hours' },
				{ value: '168', label: 'Last 7 days' }
			]}
			onchange={(value) => (hours = value === '1' ? 1 : value === '168' ? 168 : 24)}
		/>
		{#if history.recorded}
			<ul class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
				{#each Object.values(states) as state (state.label)}
					<li class="flex items-center gap-1.5">
						<span class={['size-3 rounded-sm', state.class]} aria-hidden="true"></span>{state.label}
					</li>
				{/each}
			</ul>
		{/if}
	</div>
	{#if !history.recorded}
		<p class="text-sm text-muted-foreground">
			This installation runs its detector separately, so it does not know when cameras were watched.
			Recordings are shown.
		</p>
	{/if}

	<ul class="flex flex-col gap-4">
		{#each rows as row (row.id)}
			{@const watched = watchedTime(row.stretches)}
			<li class="grid gap-x-4 gap-y-1.5 md:grid-cols-[11rem_minmax(0,1fr)] md:items-center">
				<div class="flex min-w-0 items-baseline justify-between gap-3 md:flex-col md:gap-0">
					<p class="min-w-0 truncate text-sm font-semibold">{row.label}</p>
					{#if history.recorded && row.id}
						<p class="shrink-0 text-xs text-muted-foreground">
							{watched ? `Watched ${duration(watched)}` : 'Not watched'}
						</p>
					{/if}
				</div>
				<div class="relative h-10 overflow-hidden rounded-md bg-muted">
					{#each row.stretches as stretch (stretch.from)}
						<div
							class={['absolute inset-y-0', states[stretch.state].class]}
							style={`left: ${place(stretch.from)}%; width: ${place(stretch.to) - place(stretch.from)}%`}
							title={`${moment(stretch.from)} – ${moment(stretch.to)} · ${states[stretch.state].label}`}
						></div>
					{/each}
					{#each ticks as tick (tick.at)}
						<div
							class="absolute inset-y-0 w-px bg-foreground/10"
							style={`left: ${tick.at}%`}
							aria-hidden="true"
						></div>
					{/each}
					{#each shown(row.detections) as detection (detectionKey(detection))}
						{@const label = `${moment(detection.start)} · ${detection.type} · ${percent(detection.confidence)}`}
						<button
							type="button"
							class={[
								'absolute inset-y-1.5 min-w-1.5 rounded-sm bg-category-foreground ring-1 ring-background outline-none hover:inset-y-0.5 focus-visible:ring-[3px] focus-visible:ring-ring/70',
								detection.stage === 'rejected' && 'opacity-40'
							]}
							style={`left: ${place(detection.start)}%; width: ${(detection.duration * 100000) / span}%; --badge-hue: ${badgeHue(colorSeeds[detection.type] ?? detection.type)}`}
							title={label}
							aria-label={`Play recording: ${label}`}
							onclick={() => (selected = detectionKey(detection))}
						></button>
					{/each}
				</div>
			</li>
		{/each}
		<li class="grid gap-x-4 md:grid-cols-[11rem_minmax(0,1fr)]" aria-hidden="true">
			<span></span>
			<div class="relative h-4 text-xs text-muted-foreground">
				{#each ticks as tick (tick.at)}
					<span class="absolute -translate-x-1/2 whitespace-nowrap" style={`left: ${tick.at}%`}>
						{tick.label}
					</span>
				{/each}
			</div>
		</li>
	</ul>
</div>

<RecordingViewer
	{entries}
	bind:selected
	{colorSeeds}
	onreview={(entry) => (reviewed[detectionKey(entry)] = entry)}
	onremove={(entry) => removed.push(detectionKey(entry))}
/>

<style>
	.history-hatched {
		background-image: repeating-linear-gradient(135deg, currentColor 0 2px, transparent 2px 7px);
	}
</style>

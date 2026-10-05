<script lang="ts">
	import { ArrowUp, Film } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import * as Empty from '$lib/components/ui/empty';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import {
		getDetectionPage,
		getTypes,
		getRecordingPresets,
		getDetectionReviews
	} from '$lib/remote/detections.remote';
	import { STAGES } from '$lib/schema';
	import {
		detectionKey,
		mergeDetections,
		reviewedStage,
		stageLabel,
		type Detection
	} from '$lib/detections';
	import { resolve } from '$app/paths';
	import { onMount, untrack } from 'svelte';
	import ExportRecordings from '$lib/components/export-recordings.svelte';
	import FilterChips from '$lib/components/filter-chips.svelte';
	import MonitoringBanner from '$lib/components/monitoring-banner.svelte';
	import PageHeader from '$lib/components/page-header.svelte';
	import { dayHeading, plural } from '$lib/format';
	import { getCameras } from '$lib/remote/stream.remote';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import type { Action } from 'svelte/action';
	import RecordingCard from './recording-card.svelte';
	import RecordingViewer from './recording-viewer.svelte';
	import { categoryName } from './media';
	import { SvelteMap, SvelteURLSearchParams } from 'svelte/reactivity';

	const PAGE_SIZE = 24;

	const type = $derived(page.url.searchParams.get('type') || undefined);
	const stage = $derived(STAGES.find((value) => value === page.url.searchParams.get('stage')));
	const [types, cameras, recordingPresets] = $derived(
		await Promise.all([getTypes(), getCameras(), getRecordingPresets()])
	);

	let entries = $state<Detection[]>([]);
	let isLoading = $state(true);
	let hasMore = $state(true);
	let nextOffset = $state(0);
	let errorMessage = $state<string | null>(null);
	let requestVersion = 0;
	let reviewVersion = 0;
	let hasNewRecordings = $state(false);
	let refreshError = $state(false);
	let archiveWarnings = $state<string[]>([]);
	let viewing = $state<string | null>(null);

	const detectionsByDay = $derived.by(() => {
		const dayDetections = new SvelteMap<string, Detection[]>();
		for (const detection of entries) {
			const day = String(detection.timestamp).split('T')[0];
			if (!dayDetections.has(day)) {
				dayDetections.set(day, []);
			}
			dayDetections.set(day, [...(dayDetections.get(day) ?? []), detection]);
		}
		return Array.from(dayDetections.entries());
	});

	function reviewed(updated: Detection) {
		reviewVersion += 1;
		const before = entries.length;
		entries = entries
			.map((entry) => {
				if (
					detectionKey(entry) !== detectionKey(updated) &&
					(!updated.event_id || entry.event_id !== updated.event_id)
				)
					return entry;
				return {
					...entry,
					review: updated.review,
					stage: reviewedStage(entry.archiveStage, updated.review)
				};
			})
			.filter((entry) => !stage || entry.stage === stage);
		nextOffset -= before - entries.length;
	}

	async function loadNextPage(reset = false, filters = { type, stage }) {
		if (!reset && (isLoading || !hasMore)) {
			return;
		}

		if (reset) {
			requestVersion += 1;
			hasNewRecordings = false;
			entries = [];
			nextOffset = 0;
			hasMore = true;
			errorMessage = null;
		}
		const version = requestVersion;

		isLoading = true;
		errorMessage = null;

		try {
			const query = getDetectionPage({
				...filters,
				offset: reset ? 0 : nextOffset,
				limit: PAGE_SIZE
			});
			await query.refresh();
			const result = await query;
			archiveWarnings = result.warnings ?? [];

			if (version !== requestVersion) {
				return;
			}

			const current = new Set(entries.map(detectionKey));
			entries = reset
				? result.items
				: [...entries, ...result.items.filter((entry) => !current.has(detectionKey(entry)))];
			nextOffset = result.nextOffset;
			hasMore = result.hasMore;
		} catch (error) {
			if (version === requestVersion) {
				errorMessage = error instanceof Error ? error.message : 'Failed to load recordings.';
			}
		} finally {
			if (version === requestVersion) {
				isLoading = false;
			}
		}
	}

	async function refreshRecordings() {
		if (isLoading || document.visibilityState !== 'visible') return;
		const version = requestVersion;
		const reviewsVersion = reviewVersion;
		try {
			// Refresh loaded recordings too, including those below the first page, without replacing media.
			const reviews = [];
			for (let offset = 0; offset < entries.length; offset += 100) {
				const addresses = entries
					.slice(offset, offset + 100)
					.map(({ type, archiveStage, timestamp }) => ({ type, archiveStage, timestamp }));
				const query = getDetectionReviews(addresses);
				await query.refresh();
				reviews.push(...(await query));
			}
			const query = getDetectionPage({ type, stage, offset: 0, limit: PAGE_SIZE });
			await query.refresh();
			const result = await query;
			if (version !== requestVersion || reviewsVersion !== reviewVersion) return;
			const byAddress = new Map(reviews.map((entry) => [detectionKey(entry), entry.review]));
			const before = entries.length;
			entries = entries
				.map((entry) => {
					if (!byAddress.has(detectionKey(entry))) return entry;
					const review = byAddress.get(detectionKey(entry)) ?? null;
					return {
						...entry,
						review,
						stage: reviewedStage(entry.archiveStage, review)
					};
				})
				.filter((entry) => !stage || entry.stage === stage);
			nextOffset -= before - entries.length;
			const current = new Set(entries.map(detectionKey));
			const added = result.items.filter((item) => !current.has(detectionKey(item)));
			refreshError = false;
			if (!added.length) return;
			const overlaps = result.items.some((item) => current.has(detectionKey(item)));
			// Do not move recordings under someone who is watching or has scrolled down.
			if (viewing !== null || window.scrollY > 80 || (entries.length > 0 && !overlaps)) {
				hasNewRecordings = true;
				return;
			}
			entries = mergeDetections(result.items, entries);
			nextOffset += added.length;
			hasMore ||= result.hasMore;
			await getTypes().refresh();
		} catch {
			refreshError = true;
		}
	}

	onMount(() => {
		let active = true;
		let timer: ReturnType<typeof setTimeout>;
		async function refresh() {
			await refreshRecordings();
			if (active) timer = setTimeout(refresh, 10000);
		}
		timer = setTimeout(refresh, 10000);
		return () => {
			active = false;
			clearTimeout(timer);
		};
	});

	async function updateSearchParams(type?: string, stage?: string) {
		const searchParams = new SvelteURLSearchParams(page.url.searchParams);

		if (type) {
			searchParams.set('type', type);
		} else {
			searchParams.delete('type');
		}

		if (stage) {
			searchParams.set('stage', stage);
		} else {
			searchParams.delete('stage');
		}

		const search = searchParams.toString();
		const nextUrl = resolve(`/detections${search ? `?${search}` : ''}`);
		const currentUrl = `${page.url.pathname}${page.url.search}`;

		if (nextUrl !== currentUrl) {
			await goto(nextUrl, {
				replaceState: true,
				noScroll: true,
				keepFocus: true,
				invalidateAll: false
			});
		}
	}

	const infiniteTrigger: Action<HTMLDivElement> = (node) => {
		const shouldLoadMore = () =>
			window.scrollY > 0 || document.documentElement.scrollHeight <= window.innerHeight + 32;

		const observer = new IntersectionObserver(
			([entry]) => {
				if (entry?.isIntersecting && shouldLoadMore()) {
					void loadNextPage();
				}
			},
			{ rootMargin: '200px 0px' }
		);

		observer.observe(node);

		return {
			destroy() {
				observer.disconnect();
			}
		};
	};

	$effect(() => {
		const filters = { type, stage };
		untrack(() => void loadNextPage(true, filters));
		return () => {
			requestVersion += 1;
		};
	});
</script>

<svelte:head><title>Recordings · AI Detector</title></svelte:head>

<section class="page">
	<PageHeader title="Recordings">
		{#snippet actions()}<ExportRecordings {type} {stage} />{/snippet}
	</PageHeader>
	<MonitoringBanner configured={cameras.some((camera) => camera.monitored)} />

	{#if archiveWarnings.length}
		<p role="status" class="flex flex-wrap items-center gap-3 text-sm text-danger-foreground">
			{plural(archiveWarnings.length, [
				'One recording could not be read. The others are shown below.',
				'# recordings could not be read. The others are shown below.'
			])}
			<Button href={resolve('/logs/diagnostics')} variant="outline" size="sm" download
				>Download diagnostics</Button
			>
		</p>
	{/if}

	<div class="flex flex-col gap-2.5">
		{#if types.length > 1}
			<FilterChips
				label="Category"
				value={type}
				options={[
					{ value: undefined, label: 'Everything' },
					...types.map((value) => ({ value, label: categoryName(value) }))
				]}
				onchange={(value) => updateSearchParams(value, stage)}
			/>
		{/if}
		<FilterChips
			label="Review result"
			value={stage}
			options={[
				{ value: undefined, label: 'All results' },
				...STAGES.map((value) => ({ value, label: stageLabel(value) }))
			]}
			onchange={(value) => updateSearchParams(type, value)}
		/>
	</div>

	{#if hasNewRecordings}
		<div class="sticky top-16 z-20 flex justify-center md:top-4">
			<Button class="rounded-full shadow-md" size="sm" onclick={() => loadNextPage(true)}>
				<ArrowUp data-icon="inline-start" aria-hidden="true" />Show new recordings
			</Button>
		</div>
	{/if}
	{#if refreshError}
		<p role="status" class="text-sm text-muted-foreground">
			Could not check for new recordings. Retrying automatically.
		</p>
	{/if}

	{#if entries.length === 0 && isLoading}
		<div
			class="grid gap-x-4 gap-y-7 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4"
			aria-busy="true"
			aria-label="Loading recordings"
		>
			{#each { length: 8 }, index (index)}
				<div class="flex flex-col gap-2.5">
					<Skeleton class="aspect-video rounded-xl" />
					<Skeleton class="h-4 w-2/5" />
				</div>
			{/each}
		</div>
	{:else if detectionsByDay.length === 0 && !errorMessage}
		<Empty.Root class="border border-dashed">
			<Empty.Header>
				<Empty.Media variant="icon"><Film aria-hidden="true" /></Empty.Media>
				<Empty.Title
					>{type || stage ? 'Nothing matches these filters' : 'No recordings yet'}</Empty.Title
				>
				<Empty.Description>
					{type || stage
						? 'Try another category or result.'
						: 'When a detector sees something, the clip appears here and stays until you remove it.'}
				</Empty.Description>
			</Empty.Header>
			{#if type || stage}
				<Empty.Content>
					<Button variant="outline" onclick={() => updateSearchParams()}>Show everything</Button>
				</Empty.Content>
			{/if}
		</Empty.Root>
	{:else}
		<div class="flex flex-col gap-9">
			{#each detectionsByDay as [day, recordings] (day)}
				<section class="flex flex-col gap-3.5" aria-label={dayHeading(day)}>
					<h2 class="flex items-baseline gap-2 text-sm font-semibold">
						{dayHeading(day)}
						<span class="font-normal text-muted-foreground tabular-nums">{recordings.length}</span>
					</h2>
					<div class="grid gap-x-4 gap-y-7 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
						{#each recordings as entry (detectionKey(entry))}
							<RecordingCard
								{entry}
								colorSeed={recordingPresets[entry.type]}
								onopen={() => (viewing = detectionKey(entry))}
								onreview={reviewed}
							/>
						{/each}
					</div>
				</section>
			{/each}
		</div>
	{/if}

	{#if errorMessage}
		<div class="flex flex-wrap items-center gap-3">
			<p class="text-sm font-medium text-danger-foreground">{errorMessage}</p>
			<Button type="button" size="sm" variant="outline" onclick={() => void loadNextPage()}>
				Try again
			</Button>
		</div>
	{/if}

	{#if entries.length > 0}
		<div use:infiniteTrigger class="flex min-h-12 items-center justify-center">
			{#if isLoading}
				<p class="text-sm text-muted-foreground">Loading more…</p>
			{:else if !hasMore}
				<p class="text-sm text-muted-foreground">That’s everything.</p>
			{/if}
		</div>
	{/if}
</section>

<RecordingViewer
	{entries}
	bind:selected={viewing}
	colorSeeds={recordingPresets}
	onreview={reviewed}
/>

<script lang="ts">
	import { Badge } from '$lib/components/ui/badge';
	import { Button } from '$lib/components/ui/button';
	import { getDetectionPage, getTypes } from '$lib/remote/detections.remote';
	import { STAGES } from '$lib/schema';
	import { detectionKey, mergeDetections, type Detection } from '$lib/detections';
	import { resolve } from '$app/paths';
	import { onMount, untrack } from 'svelte';
	import DetectorRuntime from '$lib/components/detector-runtime.svelte';
	import { getCameras } from '$lib/remote/stream.remote';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import type { Action } from 'svelte/action';
	import DetectionCard from './detection-card.svelte';
	import { SvelteMap, SvelteURLSearchParams } from 'svelte/reactivity';

	const PAGE_SIZE = 24;
	const dayFormatter = new Intl.DateTimeFormat(undefined, { dateStyle: 'full' });

	const type = $derived(page.url.searchParams.get('type') || undefined);
	const stage = $derived(STAGES.find((value) => value === page.url.searchParams.get('stage')));
	const [types, cameras] = $derived(await Promise.all([getTypes(), getCameras()]));

	let entries = $state<Detection[]>([]);
	let isLoading = $state(false);
	let hasMore = $state(true);
	let nextOffset = $state(0);
	let errorMessage = $state<string | null>(null);
	let requestVersion = 0;
	let hasNewRecordings = $state(false);
	let refreshError = $state(false);

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

	function capitalize(value: string) {
		return value.charAt(0).toUpperCase() + value.slice(1);
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
			const result = await getDetectionPage({
				...filters,
				offset: reset ? 0 : nextOffset,
				limit: PAGE_SIZE
			});

			if (version !== requestVersion) {
				return;
			}

			entries = reset ? result.items : mergeDetections(entries, result.items);
			nextOffset = result.nextOffset;
			hasMore = result.hasMore;
		} catch (error) {
			if (version === requestVersion) {
				errorMessage = error instanceof Error ? error.message : 'Failed to load detections.';
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
		try {
			const query = getDetectionPage({ type, stage, offset: 0, limit: PAGE_SIZE });
			await query.refresh();
			const result = await query;
			if (version !== requestVersion) return;
			const current = new Set(entries.map(detectionKey));
			const added = result.items.filter((item) => !current.has(detectionKey(item)));
			refreshError = false;
			if (!added.length) return;
			const playing = [...document.querySelectorAll('video')].some((video) => !video.paused);
			const overlaps = result.items.some((item) => current.has(detectionKey(item)));
			if (playing || window.scrollY > 80 || (entries.length > 0 && !overlaps)) {
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

<section class="flex flex-col gap-6">
	<header class="space-y-1">
		<h1 class="text-2xl font-semibold tracking-tight">Recordings</h1>
		<p class="text-sm text-muted-foreground">
			Review recorded events and play each clip. New recordings appear automatically.
		</p>
	</header>
	<DetectorRuntime configured={cameras.some((camera) => camera.monitored)} compact />
	{#if hasNewRecordings}<Button variant="outline" onclick={() => loadNextPage(true)}
			>New recordings are available — show latest</Button
		>{/if}
	{#if refreshError}<p role="status" class="text-sm text-muted-foreground">
			Could not check for new recordings. Retrying automatically.
		</p>{/if}

	<div class="flex flex-col gap-2">
		{#if types.length > 0}
			<div class="flex flex-wrap gap-2">
				{#each [undefined, ...types] as t (t)}
					<Button
						type="button"
						size="sm"
						variant={t === type ? 'default' : 'outline'}
						aria-pressed={t === type}
						onclick={() => updateSearchParams(t, stage || undefined)}
					>
						{t ? capitalize(t) : 'All categories'}
					</Button>
				{/each}
			</div>
		{/if}
		<div class="flex flex-wrap gap-2">
			{#each [undefined, ...STAGES] as s (s)}
				<Button
					type="button"
					size="sm"
					variant={s === stage ? 'default' : 'outline'}
					aria-pressed={s === stage}
					onclick={() => updateSearchParams(type || undefined, s)}
				>
					{s ? capitalize(s) : 'All stages'}
				</Button>
			{/each}
		</div>
	</div>

	{#if entries.length === 0 && isLoading}
		<h2 class="text-sm font-semibold text-muted-foreground">Loading detections...</h2>
	{:else if detectionsByDay.length === 0 && !errorMessage}
		<p class="text-sm text-muted-foreground">
			{type || stage
				? 'No recordings match these filters.'
				: 'No events recorded yet. Check the monitoring status above; recordings will appear here when an event is detected.'}
		</p>
	{:else}
		<div class="space-y-8">
			{#each detectionsByDay as dayGroup (dayGroup[0])}
				<section class="space-y-3">
					<div class="flex items-center gap-2">
						<h2 class="text-sm font-semibold text-muted-foreground">
							{dayFormatter.format(new Date(`${dayGroup[0]}T00:00:00`))}
						</h2>
						<Badge variant="outline">{dayGroup[1].length}</Badge>
					</div>
					<div class="grid gap-2 lg:grid-cols-2 2xl:grid-cols-3">
						{#each dayGroup[1] as entry (detectionKey(entry))}
							<DetectionCard {entry} />
						{/each}
					</div>
				</section>
			{/each}
		</div>
	{/if}

	{#if errorMessage}
		<div class="flex items-center gap-3">
			<p class="text-sm font-semibold text-destructive">{errorMessage}</p>
			<Button type="button" size="sm" variant="outline" onclick={() => void loadNextPage()}>
				Retry
			</Button>
		</div>
	{/if}

	{#if entries.length > 0}
		<div use:infiniteTrigger class="flex min-h-16 items-center justify-center">
			{#if isLoading}
				<p class="text-sm font-semibold text-muted-foreground">Loading more detections...</p>
			{:else if !hasMore}
				<p class="text-sm font-semibold text-muted-foreground">You reached the end.</p>
			{/if}
		</div>
	{/if}
</section>

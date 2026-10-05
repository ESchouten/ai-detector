<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { resolve } from '$app/paths';
	import { ArrowDown, Download } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import { Search } from '@lucide/svelte';
	import * as InputGroup from '$lib/components/ui/input-group';
	import { Textarea } from '$lib/components/ui/textarea';
	import PageHeader from '$lib/components/page-header.svelte';
	import * as Alert from '$lib/components/ui/alert';
	import { searchLog } from '$lib/log-search';

	let text = $state('');
	let search = $state('');
	let loading = $state(true);
	let error = $state(false);
	let following = $state(true);
	let viewport: HTMLTextAreaElement | null = $state(null);
	const visible = $derived(searchLog(text, search));

	function scrollToLatest() {
		following = true;
		viewport?.scrollTo({ top: viewport.scrollHeight });
	}

	onMount(() => {
		const controller = new AbortController();
		let timer: ReturnType<typeof setTimeout>;
		let etag = '';
		async function refresh() {
			try {
				const response = await fetch(resolve('/logs/output'), {
					headers: etag ? { 'If-None-Match': etag } : {},
					signal: controller.signal
				});
				if (response.status !== 304) {
					if (!response.ok) throw new Error('Log unavailable');
					const follow = following && !search;
					text = await response.text();
					etag = response.headers.get('ETag') ?? '';
					await tick();
					if (follow) scrollToLatest();
				}
				error = false;
			} catch {
				if (!controller.signal.aborted) error = true;
			} finally {
				loading = false;
				if (!controller.signal.aborted) timer = setTimeout(refresh, 3000);
			}
		}
		void refresh();
		return () => {
			controller.abort();
			clearTimeout(timer);
		};
	});
</script>

<svelte:head><title>Logs · AI Detector</title></svelte:head>

<section class="page">
	<PageHeader
		back={{ href: resolve('/settings'), label: 'Settings' }}
		title="Logs"
		description="Startup and recent activity, to help find what went wrong. The diagnostics download bundles this with system details for support."
	>
		{#snippet actions()}
			<Button
				href={resolve('/logs/diagnostics')}
				download="AI-Detector-diagnostics.zip"
				variant="outline"
			>
				<Download data-icon="inline-start" aria-hidden="true" />Download diagnostics
			</Button>
		{/snippet}
	</PageHeader>
	<InputGroup.Root class="max-w-md">
		<InputGroup.Addon><Search aria-hidden="true" /></InputGroup.Addon>
		<InputGroup.Input
			type="search"
			placeholder="Search logs…"
			aria-label="Search logs"
			bind:value={search}
		/>
	</InputGroup.Root>
	{#if error}
		<Alert.Root variant="destructive">
			<Alert.Title>Logs could not be refreshed</Alert.Title>
			<Alert.Description>
				Check that AI Detector is still open. Retrying automatically.
			</Alert.Description>
		</Alert.Root>
	{/if}
	<Textarea
		bind:ref={viewport}
		aria-label="Detector logs"
		readonly
		onscroll={({ currentTarget }) =>
			(following =
				currentTarget.scrollHeight - currentTarget.scrollTop - currentTarget.clientHeight < 32)}
		class="h-[62dvh] min-h-64 resize-none bg-card font-mono text-xs leading-relaxed md:text-xs"
		value={visible ||
			(loading
				? 'Loading logs…'
				: search.trim()
					? 'No matching log entries.'
					: 'No diagnostic output yet. Logs appear when monitoring starts.')}
	/>
	<div class="flex min-h-8 items-center justify-between gap-3">
		<p class="text-xs text-muted-foreground">
			{search.trim()
				? 'Matching messages include their error details.'
				: 'Updates automatically. Scroll up to read earlier output.'}
		</p>
		{#if !following && !search.trim()}
			<Button variant="outline" size="sm" onclick={scrollToLatest}>
				<ArrowDown data-icon="inline-start" aria-hidden="true" />Latest
			</Button>
		{/if}
	</div>
</section>

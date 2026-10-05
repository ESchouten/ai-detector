<script lang="ts">
	import { resolve } from '$app/paths';
	import BrandMark from './brand-mark.svelte';
	import StatusDot from './status-dot.svelte';
	import type { MonitoringSummary } from '$lib/monitoring';
	let { summary }: { summary: MonitoringSummary } = $props();
</script>

<header
	class="sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b bg-background/90 px-4 backdrop-blur md:hidden"
>
	<a href={resolve('/')} class="flex items-center gap-2.5 rounded-md outline-none">
		<BrandMark class="size-7 rounded-md" />
		<span class="text-[0.9375rem] font-semibold tracking-tight">AI Detector</span>
	</a>
	<a
		href={resolve('/status')}
		class="flex h-9 max-w-[55%] items-center gap-2 rounded-full border bg-card px-3 text-sm font-medium outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
	>
		<StatusDot tone={summary.tone} />
		<span class="truncate" role="status">{summary.label}</span>
	</a>
</header>

<script lang="ts">
	import type { Snippet } from 'svelte';
	import { ChevronLeft } from '@lucide/svelte';
	let {
		title,
		description,
		back,
		actions
	}: {
		/** Also names the browser tab. */
		title: string;
		description?: string;
		/** A resolved link to the page this one belongs to. */
		back?: { href: string; label: string };
		actions?: Snippet;
	} = $props();
</script>

<svelte:head><title>{title} · AI Detector</title></svelte:head>

<header class="flex flex-col gap-3">
	{#if back}
		<a
			href={back.href}
			class="-ml-1 inline-flex items-center gap-1 self-start rounded-md pr-2 text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50"
		>
			<ChevronLeft class="size-4" aria-hidden="true" />{back.label}
		</a>
	{/if}
	<div class="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
		<div class="flex min-w-0 flex-col gap-1">
			<h1 class="text-2xl font-semibold tracking-tight text-balance">{title}</h1>
			{#if description}
				<p class="max-w-prose text-sm leading-relaxed text-pretty text-muted-foreground">
					{description}
				</p>
			{/if}
		</div>
		{#if actions}
			<div class="flex shrink-0 flex-wrap items-center gap-2">{@render actions()}</div>
		{/if}
	</div>
</header>

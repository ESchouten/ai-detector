<script lang="ts">
	import type { Snippet } from 'svelte';
	import * as Card from '$lib/components/ui/card';
	import { fade } from 'svelte/transition';
	import { cn } from '$lib/utils';

	type Props = {
		children: Snippet;
		overlay?: Snippet;
		hide?: boolean;
		class?: string;
	};

	let { children, overlay, hide = false, class: className }: Props = $props();
</script>

<Card.Root class={cn('relative gap-0 overflow-hidden p-0', className)}>
	{@render children()}

	{#if !hide && overlay}
		<div
			class="pointer-events-none absolute inset-x-0 top-0 z-10 bg-linear-to-b from-black/80 via-black/45 to-transparent p-3 text-white"
			transition:fade
		>
			{@render overlay()}
		</div>
	{/if}
</Card.Root>

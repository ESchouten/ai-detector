<script lang="ts" module>
	import type { StatusTone } from '$lib/monitoring';
	const colors: Record<StatusTone, string> = {
		ok: 'bg-status-ok',
		busy: 'bg-status-idle',
		warn: 'bg-status-warn',
		bad: 'bg-status-bad',
		idle: 'bg-status-idle'
	};
</script>

<script lang="ts">
	import { LoaderCircle } from '@lucide/svelte';
	import { cn } from '$lib/utils';
	let { tone, class: className }: { tone: StatusTone; class?: string } = $props();
</script>

{#if tone === 'busy'}
	<LoaderCircle
		class={cn('size-3.5 shrink-0 animate-spin text-muted-foreground', className)}
		aria-hidden="true"
	/>
{:else}
	<span class={cn('relative flex size-2.5 shrink-0', className)} aria-hidden="true">
		{#if tone === 'ok'}
			<span
				class="absolute inline-flex size-full animate-ping rounded-full bg-status-ok opacity-40 motion-reduce:hidden"
			></span>
		{/if}
		<span class={cn('relative inline-flex size-full rounded-full', colors[tone])}></span>
	</span>
{/if}

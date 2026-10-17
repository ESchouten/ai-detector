<script lang="ts">
	import CctvIcon from '@lucide/svelte/icons/cctv';
	import { cn } from '$lib/utils';
	let { class: className }: { class?: string } = $props();
</script>

<span
	class={cn(
		'flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground',
		className
	)}
	aria-hidden="true"
>
	<CctvIcon class="size-[1.125rem]" />
</span>

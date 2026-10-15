<script lang="ts" generics="T extends string">
	import type { Component } from 'svelte';
	// One choice out of a few, side by side: the appearance, or a preset's mode.
	let {
		label,
		options,
		value,
		onchange,
		disabled = false
	}: {
		label: string;
		options: readonly { value: T; label: string; icon?: Component }[];
		value: T | undefined;
		onchange: (value: T) => void;
		disabled?: boolean;
	} = $props();
</script>

<div role="group" aria-label={label} class="flex flex-wrap rounded-lg border bg-muted/60 p-0.5">
	{#each options as option (option.value)}
		<button
			type="button"
			aria-pressed={value === option.value}
			{disabled}
			onclick={() => onchange(option.value)}
			class="flex h-8 items-center gap-1.5 rounded-md px-2.5 text-sm font-medium text-muted-foreground outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-60 aria-pressed:bg-background aria-pressed:text-foreground aria-pressed:shadow-xs"
		>
			{#if option.icon}<option.icon class="size-4" aria-hidden="true" />{/if}{option.label}
		</button>
	{/each}
</div>

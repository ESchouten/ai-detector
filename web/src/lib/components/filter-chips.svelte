<script lang="ts" generics="Value extends string">
	import type { Component } from 'svelte';
	import { X } from '@lucide/svelte';
	import { cn } from '$lib/utils';

	// A short list to filter by, as chips that stay on one scrollable line on a phone. Nothing
	// chosen shows everything, and pressing the chosen chip again clears it, unless one is required.
	let {
		label,
		options,
		value,
		required = false,
		onchange
	}: {
		label: string;
		options: { value: Value; label: string; icon?: Component; iconClass?: string }[];
		value: Value | undefined;
		required?: boolean;
		onchange: (value: Value | undefined) => void;
	} = $props();
</script>

<div
	role="group"
	aria-label={label}
	class="-mx-4 flex gap-1.5 overflow-x-auto px-4 [scrollbar-width:none] md:mx-0 md:flex-wrap md:px-0"
>
	{#each options as option (option.value)}
		{@const selected = option.value === value}
		<button
			type="button"
			aria-pressed={selected}
			onclick={() => onchange(selected && !required ? undefined : option.value)}
			class={[
				'inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border px-3.5 text-sm font-medium whitespace-nowrap transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50',
				selected
					? 'border-transparent bg-foreground text-background'
					: 'bg-card text-muted-foreground hover:bg-accent hover:text-accent-foreground'
			]}
		>
			{#if option.icon}
				<option.icon
					class={cn('size-4', option.iconClass, selected && 'text-background')}
					aria-hidden="true"
				/>
			{/if}
			{option.label}
			{#if selected && !required}<X class="-mr-1 size-3.5 opacity-70" aria-hidden="true" />{/if}
		</button>
	{/each}
</div>

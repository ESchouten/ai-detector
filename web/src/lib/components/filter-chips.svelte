<script lang="ts" generics="Value extends string">
	// One choice from a short list, as chips that stay on one scrollable line on a phone.
	let {
		label,
		options,
		value,
		onchange
	}: {
		label: string;
		options: { value: Value | undefined; label: string }[];
		value: Value | undefined;
		onchange: (value: Value | undefined) => void;
	} = $props();
</script>

<div
	role="group"
	aria-label={label}
	class="-mx-4 flex gap-1.5 overflow-x-auto px-4 [scrollbar-width:none] md:mx-0 md:flex-wrap md:px-0"
>
	{#each options as option (option.value ?? '')}
		{@const selected = option.value === value}
		<button
			type="button"
			aria-pressed={selected}
			onclick={() => onchange(option.value)}
			class={[
				'h-8 shrink-0 rounded-full border px-3.5 text-sm font-medium whitespace-nowrap transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50',
				selected
					? 'border-transparent bg-foreground text-background'
					: 'bg-card text-muted-foreground hover:bg-accent hover:text-accent-foreground'
			]}
		>
			{option.label}
		</button>
	{/each}
</div>

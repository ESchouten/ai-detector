<script lang="ts">
	import { resolve } from '$app/paths';
	import { Check } from '@lucide/svelte';
	import type { SetupStep } from '$lib/setup';
	let {
		current,
		hasCameras,
		disabled = false
	}: {
		current: SetupStep;
		hasCameras: boolean;
		disabled?: boolean;
	} = $props();
	const steps = [
		{ id: 'cameras', label: 'Cameras' },
		{ id: 'detectors', label: 'Detection' },
		{ id: 'finish', label: 'Start' }
	] as const;
	const position = $derived(steps.findIndex((step) => step.id === current));
</script>

{#snippet marker(step: (typeof steps)[number], index: number)}
	<span
		class={[
			'flex size-7 shrink-0 items-center justify-center rounded-full border text-xs tabular-nums',
			current === step.id
				? 'border-primary bg-primary text-primary-foreground'
				: index < position
					? 'border-primary text-primary'
					: 'bg-card'
		]}
	>
		{#if index < position}<Check class="size-3.5" aria-hidden="true" />{:else}{index + 1}{/if}
	</span>
	<span class={current === step.id ? '' : 'hidden sm:inline'}>{step.label}</span>
{/snippet}

<nav aria-label="Setup progress">
	<ol class="flex items-center gap-2 sm:gap-3">
		{#each steps as step, index (step.id)}
			{#if index}
				<li
					aria-hidden="true"
					class={[
						'h-px min-w-4 flex-1 sm:max-w-16',
						index <= position ? 'bg-primary' : 'bg-border'
					]}
				></li>
			{/if}
			<li>
				{#if disabled || (step.id !== 'cameras' && !hasCameras)}
					<span class="flex items-center gap-2 pr-1 text-sm font-medium text-muted-foreground/70">
						{@render marker(step, index)}
					</span>
				{:else}
					<a
						href={resolve(`/setup?step=${step.id}`)}
						aria-current={current === step.id ? 'step' : undefined}
						class="flex items-center gap-2 rounded-full pr-1 text-sm font-medium text-muted-foreground outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 aria-[current=step]:text-foreground"
					>
						{@render marker(step, index)}
					</a>
				{/if}
			</li>
		{/each}
	</ol>
</nav>

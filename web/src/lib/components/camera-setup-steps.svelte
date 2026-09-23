<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	let {
		current,
		canContinue,
		disabled,
		onchoose
	}: {
		current: 1 | 2 | 3;
		canContinue: boolean;
		disabled: boolean;
		onchoose: (step: 1 | 2) => void;
	} = $props();
</script>

<nav aria-label="Camera setup progress">
	<ol class="grid grid-cols-3 gap-2">
		{#each ['Connect camera', 'Choose monitoring', 'Finish setup'] as label, index (label)}
			<li class="min-w-0">
				<Button
					type="button"
					variant={current === index + 1 ? 'secondary' : 'ghost'}
					class="h-auto w-full flex-col items-start gap-1 px-3 py-3 text-left whitespace-normal sm:px-4"
					aria-current={current === index + 1 ? 'step' : undefined}
					disabled={disabled || current === 3 || index === 2 || (index === 1 && !canContinue)}
					onclick={() => onchoose(index === 0 ? 1 : 2)}
				>
					<span class="text-xs text-muted-foreground">Step {index + 1}</span>
					<span>{label}</span>
				</Button>
			</li>
		{/each}
	</ol>
</nav>

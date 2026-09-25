<script lang="ts">
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
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
		{ id: 'detectors', label: 'Detectors' },
		{ id: 'finish', label: 'Finish setup' }
	] as const;
</script>

<nav aria-label="Setup progress">
	<ol class="grid grid-cols-3 gap-2">
		{#each steps as step, index (step.id)}
			<li class="min-w-0">
				<Button
					href={resolve(`/setup?step=${step.id}`)}
					variant={current === step.id ? 'secondary' : 'ghost'}
					class="h-full w-full flex-col items-start gap-1 px-3 py-3 text-left whitespace-normal sm:px-4"
					aria-current={current === step.id ? 'step' : undefined}
					disabled={disabled || (step.id !== 'cameras' && !hasCameras)}
				>
					<span class="text-xs text-muted-foreground">Step {index + 1}</span>
					<span>{step.label}</span>
				</Button>
			</li>
		{/each}
	</ol>
</nav>

<script lang="ts">
	import { onMount } from 'svelte';
	import { Smartphone, X } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import { deviceLacksHomeScreenIcon } from '$lib/home-screen';
	import HomeScreenGuide from './home-screen-guide.svelte';

	// Offered once on a phone or tablet, until it is done or declined. Settings keeps the way in.
	const DECLINED = 'ai-detector.home-screen-hint';
	let offered = $state(false);
	let guide = $state<HomeScreenGuide>();
	onMount(() => {
		offered = !localStorage.getItem(DECLINED) && deviceLacksHomeScreenIcon();
	});

	function decline() {
		localStorage.setItem(DECLINED, 'declined');
		offered = false;
	}
</script>

{#if offered}
	<div class="mb-5 flex items-center gap-3 rounded-xl border bg-card py-2.5 pr-2 pl-4">
		<Smartphone class="size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
		<p class="min-w-0 flex-1 text-sm font-medium">Put AI Detector on your home screen</p>
		<Button variant="outline" size="sm" onclick={() => guide?.show()}>Show me how</Button>
		<Button variant="ghost" size="icon-sm" aria-label="Not now" onclick={decline}>
			<X aria-hidden="true" />
		</Button>
	</div>
	<HomeScreenGuide bind:this={guide} />
{/if}

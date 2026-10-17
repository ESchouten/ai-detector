<script lang="ts">
	import type { DiscoveredCamera } from '$lib/cameras';
	import { Button } from '$lib/components/ui/button';
	import { LoaderCircle, Search } from '@lucide/svelte';
	import * as RadioGroup from '$lib/components/ui/radio-group';
	let {
		candidates,
		address,
		finding,
		discoveryMessage,
		manualAddress,
		disabled,
		onSearch,
		onSelect,
		onToggleManual
	}: {
		candidates: DiscoveredCamera[];
		address: string;
		finding: boolean;
		discoveryMessage: string;
		manualAddress: boolean;
		disabled: boolean;
		onSearch: () => void;
		onSelect: (address: string) => void;
		onToggleManual: () => void;
	} = $props();
</script>

<section aria-labelledby="camera-discovery-title" class="flex flex-col gap-3">
	<div class="flex flex-wrap items-center justify-between gap-3">
		<h3 id="camera-discovery-title" class="text-sm font-medium">Cameras on your network</h3>
		<Button variant="outline" size="sm" disabled={finding || disabled} onclick={onSearch}>
			{#if finding}<LoaderCircle
					data-icon="inline-start"
					class="animate-spin"
					aria-hidden="true"
				/>{:else}<Search data-icon="inline-start" aria-hidden="true" />{/if}
			{finding ? 'Searching…' : 'Search again'}
		</Button>
	</div>
	{#if discoveryMessage}
		<p role="status" class="text-sm text-muted-foreground">{discoveryMessage}</p>
	{/if}
	{#if candidates.length}
		<RadioGroup.Root
			value={address}
			aria-label="Discovered cameras"
			class="-mx-2 gap-0"
			{disabled}
			onValueChange={onSelect}
		>
			{#each candidates as camera, index (camera.address)}
				<label
					for={`camera-choice-${index}`}
					class="flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2.5 hover:bg-accent"
				>
					<RadioGroup.Item id={`camera-choice-${index}`} value={camera.address} />
					<span class="flex min-w-0 flex-col">
						<span class="text-sm font-medium">{camera.name}</span>
						<span class="text-xs break-all text-muted-foreground">{camera.address}</span>
					</span>
				</label>
			{/each}
		</RadioGroup.Root>
	{/if}
	{#if candidates.length || !manualAddress}
		<Button
			variant="ghost"
			size="sm"
			class="self-start"
			aria-expanded={manualAddress}
			{disabled}
			onclick={onToggleManual}
			>{manualAddress ? 'Choose from the list instead' : 'Enter a stream URL instead'}</Button
		>
	{/if}
</section>

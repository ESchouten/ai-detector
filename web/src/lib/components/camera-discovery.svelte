<script lang="ts">
	import type { DiscoveredCamera } from '$lib/cameras';
	import { Button } from '$lib/components/ui/button';
	import { Search } from '@lucide/svelte';
	import * as Field from '$lib/components/ui/field';
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

<section aria-labelledby="camera-discovery-title" class="flex flex-col gap-4">
	<div class="flex flex-col gap-2">
		<div class="flex flex-wrap items-center justify-between gap-3">
			<h2 id="camera-discovery-title" class="font-medium">Available cameras</h2>
			<Button
				type="button"
				variant="outline"
				size="sm"
				disabled={finding || disabled}
				onclick={onSearch}
			>
				<Search data-icon="inline-start" />{finding ? 'Searching…' : 'Search again'}
			</Button>
		</div>
		{#if discoveryMessage}<p role="status" class="text-sm text-muted-foreground">
				{discoveryMessage}
			</p>{/if}
	</div>
	{#if candidates.length}
		<RadioGroup.Root
			value={address}
			aria-label="Discovered cameras"
			{disabled}
			onValueChange={onSelect}
		>
			{#each candidates as camera, index (camera.address)}
				<Field.Field orientation="horizontal">
					<RadioGroup.Item id={`camera-choice-${index}`} value={camera.address} />
					<Field.Label for={`camera-choice-${index}`} class="min-w-0 cursor-pointer">
						<Field.Content>
							<Field.Title>{camera.name}</Field.Title>
							<Field.Description class="break-all">{camera.address}</Field.Description>
						</Field.Content>
					</Field.Label>
				</Field.Field>
			{/each}
		</RadioGroup.Root>
	{/if}
	{#if candidates.length || !manualAddress}<Button
			type="button"
			variant="outline"
			class="self-start"
			aria-expanded={manualAddress}
			{disabled}
			onclick={onToggleManual}
			>{manualAddress ? 'Hide manual entry' : 'Enter camera manually'}</Button
		>{/if}
</section>

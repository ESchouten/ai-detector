<script lang="ts">
	import { resolve } from '$app/paths';
	import { ChevronDown, X } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import * as DropdownMenu from '$lib/components/ui/dropdown-menu';
	import * as Dialog from '$lib/components/ui/dialog';
	import LiveDetections from './live-detections.svelte';
	let {
		id,
		label,
		monitored,
		setupComplete
	}: {
		id: string;
		label: string;
		monitored: boolean;
		setupComplete: boolean;
	} = $props();
	let showDetections = $state(false);
</script>

<DropdownMenu.Root>
	<DropdownMenu.Trigger>
		{#snippet child({ props })}
			<Button {...props} variant="secondary" size="sm" aria-label={`Manage ${label}`}>
				Manage <ChevronDown data-icon="inline-end" />
			</Button>
		{/snippet}
	</DropdownMenu.Trigger>
	<DropdownMenu.Content align="end">
		<DropdownMenu.Group>
			{#if !setupComplete}
				<DropdownMenu.Item>
					{#snippet child({ props })}<a
							{...props}
							href={resolve(monitored ? '/setup?step=finish' : '/setup?step=detectors')}
							>Finish setup</a
						>{/snippet}
				</DropdownMenu.Item>
			{/if}
			<DropdownMenu.Item>
				{#snippet child({ props })}<a {...props} href={resolve(`/streams/add?id=${id}`)}
						>Camera settings</a
					>{/snippet}
			</DropdownMenu.Item>
			<DropdownMenu.Item>
				{#snippet child({ props })}<a {...props} href={resolve('/detectors')}>Detectors</a
					>{/snippet}
			</DropdownMenu.Item>
			{#if monitored}
				<DropdownMenu.Item>
					{#snippet child({ props })}<a {...props} href={resolve('/notifications')}>Phone alerts</a
						>{/snippet}
				</DropdownMenu.Item>
				<DropdownMenu.Item onSelect={() => (showDetections = true)}
					>Live detections</DropdownMenu.Item
				>
			{/if}
		</DropdownMenu.Group>
	</DropdownMenu.Content>
</DropdownMenu.Root>

<Dialog.Root bind:open={showDetections}>
	<Dialog.Content
		class="gap-0 overflow-hidden rounded-xl border-0 p-0 sm:max-w-3xl"
		showCloseButton={false}
	>
		<Dialog.Header class="sr-only">
			<Dialog.Title>{label}</Dialog.Title>
			<Dialog.Description>Live detections</Dialog.Description>
		</Dialog.Header>
		{#if showDetections}<LiveDetections {id} {label} />{/if}
		<Dialog.Close>
			{#snippet child({ props })}
				<Button
					{...props}
					variant="secondary"
					size="icon-sm"
					class="absolute top-3 right-3 z-20"
					aria-label="Close"
				>
					<X aria-hidden="true" />
				</Button>
			{/snippet}
		</Dialog.Close>
	</Dialog.Content>
</Dialog.Root>

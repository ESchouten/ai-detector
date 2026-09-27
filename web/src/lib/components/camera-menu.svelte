<script lang="ts">
	import { resolve } from '$app/paths';
	import { ChevronDown } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import * as DropdownMenu from '$lib/components/ui/dropdown-menu';
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
			{/if}
		</DropdownMenu.Group>
	</DropdownMenu.Content>
</DropdownMenu.Root>

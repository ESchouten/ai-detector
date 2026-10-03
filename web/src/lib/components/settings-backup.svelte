<script lang="ts">
	import { resolve } from '$app/paths';
	import { Download } from '@lucide/svelte';
	import { Button, buttonVariants } from '$lib/components/ui/button';
	import * as Dialog from '$lib/components/ui/dialog';
</script>

<Dialog.Root>
	<Dialog.Trigger class={buttonVariants({ variant: 'outline' })}>
		<Download data-icon="inline-start" aria-hidden="true" />Back up settings
	</Dialog.Trigger>
	<Dialog.Content>
		<Dialog.Header>
			<Dialog.Title>Back up settings</Dialog.Title>
			<Dialog.Description>Save your setup and confirmed herd photos in one ZIP.</Dialog.Description>
		</Dialog.Header>
		<p class="text-sm">Includes saved passwords and tokens. Keep this backup private.</p>
		<p class="text-sm text-muted-foreground">
			Recordings and model files are not included. To restore, extract the ZIP and choose Use
			existing setup in a new installation.
		</p>
		<Dialog.Footer>
			<Button href={resolve('/setup/backup')} download data-sveltekit-reload>
				<Download data-icon="inline-start" aria-hidden="true" />Download backup
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>

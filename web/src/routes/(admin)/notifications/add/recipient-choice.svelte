<script lang="ts">
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
	import * as Card from '$lib/components/ui/card';
	let { recipients, cameraId }: { recipients: { label: string }[]; cameraId: string } = $props();
	const cameraQuery = $derived(cameraId ? `&camera=${encodeURIComponent(cameraId)}` : '');
</script>

<section class="flex w-full max-w-2xl flex-col gap-6">
	<header class="flex flex-col gap-2">
		<h1 class="text-2xl font-semibold tracking-tight">Where should alerts go?</h1>
		<p class="text-muted-foreground">
			Use a connected phone or group. You do not need to create another bot for another camera.
		</p>
	</header>
	<Card.Root>
		<Card.Header
			><Card.Title>Use an existing recipient</Card.Title><Card.Description
				>Existing camera assignments will stay selected.</Card.Description
			></Card.Header
		>
		<Card.Content class="flex flex-col gap-3">
			{#each recipients as recipient (recipient.label)}<Button
					href={resolve(
						`/notifications/add?label=${encodeURIComponent(recipient.label)}${cameraQuery}`
					)}
					variant="outline">Use {recipient.label}</Button
				>{/each}
		</Card.Content>
	</Card.Root>
	<Button href={resolve(`/notifications/add?new=1${cameraQuery}`)} variant="outline"
		>Connect a new recipient</Button
	>
	<Button
		href={cameraId
			? resolve(`/setup?camera=${encodeURIComponent(cameraId)}`)
			: resolve('/notifications')}
		variant="ghost">{cameraId ? 'Back to setup' : 'Cancel'}</Button
	>
</section>

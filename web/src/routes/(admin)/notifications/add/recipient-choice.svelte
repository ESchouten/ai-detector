<script lang="ts">
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
	import * as Card from '$lib/components/ui/card';
	let { recipients, cameraId }: { recipients: { label: string }[]; cameraId: string } = $props();
	const cameraQuery = $derived(cameraId ? `&camera=${encodeURIComponent(cameraId)}` : '');
</script>

<section class="settings-page">
	<header class="flex flex-col gap-2">
		<h1 class="settings-heading">Where should alerts go?</h1>
		<p class="settings-description">
			Use a connected phone or group. You do not need to create another bot for another camera.
		</p>
	</header>
	<div class="settings-layout">
		<div class="flex min-w-0 flex-col gap-6">
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
		</div>
		<aside class="settings-aside">
			<div class="flex flex-col gap-2">
				<h2 class="text-sm font-semibold">Keep your existing connection</h2>
				<p class="text-sm text-muted-foreground">
					Choose a saved recipient to use its existing Telegram connection. You can review and
					change the cameras before saving.
				</p>
			</div>
		</aside>
	</div>
</section>

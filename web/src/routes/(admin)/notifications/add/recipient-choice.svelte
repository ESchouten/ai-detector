<script lang="ts">
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
	import * as Card from '$lib/components/ui/card';
	let {
		recipients,
		cameraId,
		setupMode
	}: { recipients: { label: string }[]; cameraId: string; setupMode: boolean } = $props();
	const cameraQuery = $derived(
		(cameraId ? `&camera=${encodeURIComponent(cameraId)}` : '') + (setupMode ? '&setup=1' : '')
	);
</script>

<section class="settings-page max-w-3xl">
	<header class="flex flex-col gap-2">
		<h1 class="settings-heading">Where should alerts go?</h1>
		<p class="settings-description">
			Use a connected phone or group. You do not need to create another bot for another camera.
		</p>
	</header>
	<div class="flex flex-col gap-6">
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
				href={resolve(setupMode ? '/setup?step=finish' : cameraId ? '/streams' : '/notifications')}
				variant="outline">Cancel</Button
			>
		</div>
	</div>
</section>

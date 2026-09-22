<script lang="ts">
	import { page } from '$app/state';
	import NotificationEditor from './notification-editor.svelte';
	import * as Alert from '$lib/components/ui/alert';
	import { getTelegram } from '$lib/remote/exporter.remote';
	const label = $derived(page.url.searchParams.get('label') ?? '');
	const saved = $derived(label ? await getTelegram({ label }) : undefined);
	const setupMode = $derived(page.url.searchParams.get('setup') === '1');
</script>

<svelte:head><title>Notification settings · AI Detector</title></svelte:head>

{#if label && !saved}
	<Alert.Root variant="destructive">
		<Alert.Title>Notification channel not found</Alert.Title>
		<Alert.Description>Return to Notifications to select a saved channel.</Alert.Description>
	</Alert.Root>
{:else}
	{#key label}
		<NotificationEditor originalLabel={label} initial={saved} {setupMode} />
	{/key}
{/if}

<script lang="ts">
	import { page } from '$app/state';
	import NotificationEditor from './notification-editor.svelte';
	import RecipientChoice from './recipient-choice.svelte';
	import * as Alert from '$lib/components/ui/alert';
	import { getTelegram, getTelegrams } from '$lib/remote/exporter.remote';
	const label = $derived(page.url.searchParams.get('label') ?? '');
	const cameraId = $derived(page.url.searchParams.get('camera') ?? '');
	const setupMode = $derived(page.url.searchParams.get('setup') === '1');
	const createNew = $derived(page.url.searchParams.get('new') === '1');
	const saved = $derived(label ? await getTelegram({ label }) : undefined);
	const recipients = await getTelegrams();
</script>

<svelte:head><title>Alert settings · AI Detector</title></svelte:head>

{#if label && !saved}
	<Alert.Root variant="destructive">
		<Alert.Title>Alert recipient not found</Alert.Title>
		<Alert.Description>Return to Alerts to select a saved recipient.</Alert.Description>
	</Alert.Root>
{:else if !label && !createNew && recipients.length}
	<RecipientChoice {recipients} {cameraId} {setupMode} />
{:else}
	{#key `${label}:${cameraId}`}
		<NotificationEditor originalLabel={label} initial={saved} {cameraId} {setupMode} />
	{/key}
{/if}

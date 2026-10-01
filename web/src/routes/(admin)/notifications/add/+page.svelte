<script lang="ts">
	import { page } from '$app/state';
	import NotificationEditor from '$lib/components/notification-editor.svelte';
	import RecipientChoice from './recipient-choice.svelte';
	import * as Alert from '$lib/components/ui/alert';
	import { getTelegrams } from '$lib/remote/exporter.remote';
	const label = $derived(page.url.searchParams.get('label') ?? '');
	const detectorLabel = $derived(page.url.searchParams.get('detector') ?? '');
	const setupMode = $derived(page.url.searchParams.get('setup') === '1');
	const createNew = $derived(page.url.searchParams.get('new') === '1');
	const recipients = $derived(await getTelegrams());
	const saved = $derived(recipients.find((recipient) => recipient.label === label));
</script>

<svelte:head><title>Alert settings · AI Detector</title></svelte:head>

{#if label && !saved}
	<Alert.Root variant="destructive">
		<Alert.Title>Alert recipient not found</Alert.Title>
		<Alert.Description>Return to Alerts to select a saved recipient.</Alert.Description>
	</Alert.Root>
{:else if !label && !createNew && recipients.length}
	<RecipientChoice {recipients} {detectorLabel} {setupMode} />
{:else}
	{#key `${label}:${detectorLabel}`}
		<NotificationEditor originalLabel={label} initial={saved} {detectorLabel} {setupMode} />
	{/key}
{/if}

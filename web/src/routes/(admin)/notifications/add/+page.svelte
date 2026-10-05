<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import NotificationEditor from '$lib/components/notification-editor.svelte';
	import PageHeader from '$lib/components/page-header.svelte';
	import * as Alert from '$lib/components/ui/alert';
	import { getTelegrams } from '$lib/remote/alerts.remote';
	const label = $derived(page.url.searchParams.get('label') ?? '');
	const recipients = $derived(await getTelegrams());
	const saved = $derived(recipients.find((recipient) => recipient.label === label));
	const back = { href: resolve('/notifications'), label: 'Alerts' };
</script>

<svelte:head><title>{saved?.label ?? 'Add recipient'} · AI Detector</title></svelte:head>

<section class="page-narrow">
	{#if label && !saved}
		<PageHeader {back} title="Recipient not found" />
		<Alert.Root variant="destructive">
			<Alert.Title>Alert recipient not found</Alert.Title>
			<Alert.Description>Return to Alerts to select a saved recipient.</Alert.Description>
		</Alert.Root>
	{:else}
		<PageHeader
			{back}
			title={saved ? saved.label : 'Connect alerts'}
			description={saved
				? 'Choose which detectors send alerts here, or connect it again.'
				: 'Connect a phone, group or channel in Telegram, then choose which detectors alert it.'}
		/>
		{#key label}
			<NotificationEditor originalLabel={label} initial={saved} />
		{/key}
	{/if}
</section>

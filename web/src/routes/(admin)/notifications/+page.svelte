<script lang="ts">
	import { resolve } from '$app/paths';
	import { Bell, Plus } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import * as Empty from '$lib/components/ui/empty';
	import LinkRows from '$lib/components/link-rows.svelte';
	import PageHeader from '$lib/components/page-header.svelte';
	import { getTelegrams } from '$lib/remote/alerts.remote';
	import { getDetectors } from '$lib/remote/detector.remote';
	import { recipientDetectorLabels } from '$lib/alert-recipients';
	const [detectors, telegrams] = $derived(await Promise.all([getDetectors(), getTelegrams()]));
</script>

<section class="page-narrow">
	<PageHeader
		back={{ href: resolve('/settings'), label: 'Settings' }}
		title="Alerts"
		description="When a detector sees something, the clip is sent to these people in Telegram. They can confirm it or mark it as a false alarm right there."
	>
		{#snippet actions()}
			{#if telegrams.length}
				<Button href={resolve('/notifications/add')}>
					<Plus data-icon="inline-start" aria-hidden="true" />Add recipient
				</Button>
			{/if}
		{/snippet}
	</PageHeader>
	{#if telegrams.length}
		<LinkRows
			items={telegrams.map((telegram) => {
				const assigned = recipientDetectorLabels(detectors, telegram);
				return {
					title: telegram.label,
					href: resolve(`/notifications/add?label=${encodeURIComponent(telegram.label)}`),
					icon: Bell,
					description: assigned.length
						? `Alerts from ${assigned.join(', ')}`
						: 'Not used by a detector yet'
				};
			})}
		/>
	{:else}
		<Empty.Root class="border border-dashed">
			<Empty.Header>
				<Empty.Media variant="icon"><Bell aria-hidden="true" /></Empty.Media>
				<Empty.Title>No phone alerts yet</Empty.Title>
				<Empty.Description>
					Connect Telegram to get each event on your phone. Monitoring and recording also work
					without alerts.
				</Empty.Description>
			</Empty.Header>
			<Empty.Content>
				<Button href={resolve('/notifications/add')}>Connect your phone</Button>
			</Empty.Content>
		</Empty.Root>
	{/if}
</section>

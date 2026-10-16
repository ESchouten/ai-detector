<script lang="ts">
	import { resolve } from '$app/paths';
	import { Bell, Plus } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import * as Empty from '$lib/components/ui/empty';
	import * as Field from '$lib/components/ui/field';
	import { Switch } from '$lib/components/ui/switch';
	import LinkRows from '$lib/components/link-rows.svelte';
	import PageHeader from '$lib/components/page-header.svelte';
	import {
		getTelegrams,
		getOutageNotifications,
		saveOutageNotifications
	} from '$lib/remote/alerts.remote';
	import { errorMessage, refresh } from '$lib/remote-calls';
	import { getDetectors } from '$lib/remote/detector.remote';
	import { recipientDetectorLabels } from '$lib/alert-recipients';
	const [detectors, telegrams] = $derived(await Promise.all([getDetectors(), getTelegrams()]));
	const savedNotifications = $derived(await getOutageNotifications());
	let savingNotifications = $state<boolean | null>(null);
	let notificationError = $state('');

	async function setOutageNotifications(enabled: boolean) {
		savingNotifications = enabled;
		notificationError = '';
		try {
			await saveOutageNotifications(enabled);
			await refresh(getOutageNotifications());
		} catch (cause) {
			notificationError = errorMessage(
				cause,
				'Camera notifications could not be saved. Try again.'
			);
		} finally {
			savingNotifications = null;
		}
	}
</script>

<section class="page-narrow">
	<PageHeader
		back={{ href: resolve('/settings'), label: 'Settings' }}
		title="Alerts"
		description="When a detector sees something, the footage is sent to these people in Telegram. They can confirm it or mark it as a false alarm right there."
	>
		{#snippet actions()}
			{#if telegrams.length}
				<Button href={resolve('/notifications/add')}>
					<Plus data-icon="inline-start" aria-hidden="true" />Add recipient
				</Button>
			{/if}
		{/snippet}
	</PageHeader>
	<Field.Group class="panel p-4">
		<Field.Field orientation="horizontal" data-disabled={savingNotifications !== null}>
			<Field.Content>
				<Field.Label for="camera-offline-notifications">Camera offline notifications</Field.Label>
				<Field.Description id="camera-offline-notifications-help">
					Send a Telegram message to the camera’s alert recipients after five minutes without
					monitoring, and when monitoring resumes.
				</Field.Description>
			</Field.Content>
			<Switch
				id="camera-offline-notifications"
				checked={savingNotifications ?? savedNotifications}
				onCheckedChange={setOutageNotifications}
				disabled={savingNotifications !== null}
				aria-describedby="camera-offline-notifications-help"
			/>
		</Field.Field>
		{#if notificationError}
			<p role="alert" class="text-sm text-danger-foreground">{notificationError}</p>
		{/if}
	</Field.Group>
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

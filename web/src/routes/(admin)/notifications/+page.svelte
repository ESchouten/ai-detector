<script lang="ts">
	import { resolve } from '$app/paths';
	import { Bell, BellRing, Plus } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import * as Empty from '$lib/components/ui/empty';
	import * as Field from '$lib/components/ui/field';
	import { Switch } from '$lib/components/ui/switch';
	import LinkRows from '$lib/components/link-rows.svelte';
	import PageHeader from '$lib/components/page-header.svelte';
	import { getTelegrams, getPhoneAlarm, saveAlarmOutages } from '$lib/remote/alerts.remote';
	import { errorMessage, refresh } from '$lib/remote-calls';
	import { getDetectors } from '$lib/remote/detector.remote';
	import { recipientDetectorLabels } from '$lib/alert-recipients';
	const [detectors, telegrams, alarm] = $derived(
		await Promise.all([getDetectors(), getTelegrams(), getPhoneAlarm()])
	);
	let savingAlarmOutages = $state<boolean | null>(null);
	let notificationError = $state('');

	async function setAlarmOutages(enabled: boolean) {
		savingAlarmOutages = enabled;
		notificationError = '';
		try {
			await saveAlarmOutages(enabled);
			await refresh(getPhoneAlarm());
		} catch (cause) {
			notificationError = errorMessage(
				cause,
				'Camera notifications could not be saved. Try again.'
			);
		} finally {
			savingAlarmOutages = null;
		}
	}
</script>

<section class="page-narrow">
	<PageHeader
		back={{ href: resolve('/settings'), label: 'Settings' }}
		title="Alerts"
		description="Choose how you hear about what a detector sees: a message with the footage, a loud alarm on your phone, or both."
	/>
	<div class="flex flex-wrap items-center justify-between gap-3">
		<div class="flex flex-col gap-1">
			<h2 id="alerts-messages" class="text-base font-semibold">Messages</h2>
			<p class="text-sm text-muted-foreground">
				Through Telegram, the footage goes to these people. They can confirm it or mark it as a
				false alarm right there.
			</p>
		</div>
		{#if telegrams.length}
			<Button href={resolve('/notifications/add')}>
				<Plus data-icon="inline-start" aria-hidden="true" />Add recipient
			</Button>
		{/if}
	</div>
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
				<Empty.Title>No Telegram recipients yet</Empty.Title>
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
	<div class="flex flex-col gap-1">
		<h2 id="alerts-alarm" class="text-base font-semibold">Alarm</h2>
		<p class="text-sm text-muted-foreground">
			Through the free ntfy app, your phone rings loudly, also at night, with a picture of what the
			detector saw.
		</p>
	</div>
	<LinkRows
		items={[
			{
				title: alarm.saved ? 'Phone alarm' : 'Set up the phone alarm',
				href: resolve('/notifications/alarm'),
				icon: BellRing,
				description: !alarm.saved
					? 'Wake up for a detection with a loud alarm, through the free ntfy app.'
					: alarm.detectorLabels.length
						? `Rings for ${alarm.detectorLabels.join(', ')}`
						: 'Not used by a detector yet'
			}
		]}
	/>
	{#if alarm.saved}
		<Field.Group class="panel gap-4 p-4">
			<Field.Field orientation="horizontal" data-disabled={savingAlarmOutages !== null}>
				<Field.Content>
					<Field.Label for="camera-offline-alarm">Camera offline</Field.Label>
					<Field.Description id="camera-offline-alarm-help">
						After five minutes without monitoring, and when monitoring resumes. A normal
						notification in ntfy, without the alarm sound.
					</Field.Description>
				</Field.Content>
				<Switch
					id="camera-offline-alarm"
					checked={savingAlarmOutages ?? alarm.outages}
					onCheckedChange={setAlarmOutages}
					disabled={savingAlarmOutages !== null}
					aria-describedby="camera-offline-alarm-help"
				/>
			</Field.Field>
			{#if notificationError}
				<p role="alert" class="text-sm text-danger-foreground">{notificationError}</p>
			{/if}
		</Field.Group>
	{/if}
</section>

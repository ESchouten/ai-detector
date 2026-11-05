<script lang="ts">
	import { untrack } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { Button } from '$lib/components/ui/button';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import * as Alert from '$lib/components/ui/alert';
	import * as Field from '$lib/components/ui/field';
	import ConfirmRemove from './confirm-remove.svelte';
	import {
		deletePhoneAlarm,
		getPhoneAlarm,
		savePhoneAlarm,
		testPhoneAlarm
	} from '$lib/remote/alerts.remote';
	import { getDetectors } from '$lib/remote/detector.remote';
	import { errorMessage, refresh } from '$lib/remote-calls';

	let {
		inline = false,
		onSaved,
		onCancel
	}: {
		/** Only set up the alarm, inside an editor that chooses its detectors itself. */
		inline?: boolean;
		onSaved: () => void | Promise<void>;
		onCancel: () => void;
	} = $props();
	const alarm = await getPhoneAlarm();
	const detectors = await getDetectors();
	let detectorLabels = $state(
		untrack(() => (!alarm.saved ? detectors.map(({ meta }) => meta.label) : alarm.detectorLabels))
	);
	let testing = $state(false);
	let tested = $state(false);
	let received = $state(untrack(() => alarm.saved));
	let pending = $state(false);
	let error = $state('');

	async function test() {
		testing = true;
		error = '';
		try {
			await testPhoneAlarm({ topic: alarm.topic });
			tested = true;
		} catch (cause) {
			error = errorMessage(cause, 'Could not send the test alarm.');
		} finally {
			testing = false;
		}
	}
	async function save(event: SubmitEvent) {
		event.preventDefault();
		pending = true;
		error = '';
		try {
			await savePhoneAlarm({
				topic: alarm.topic,
				detectorLabels: inline ? alarm.detectorLabels : detectorLabels
			});
			await refresh(getPhoneAlarm(), getDetectors());
			if (!inline) toast.success('Phone alarm saved.');
			await onSaved();
		} catch (cause) {
			error = errorMessage(cause, 'Could not save the phone alarm. Your choices are still here.');
		} finally {
			pending = false;
		}
	}
	async function remove() {
		pending = true;
		error = '';
		try {
			await deletePhoneAlarm();
			await refresh(getPhoneAlarm(), getDetectors());
			onCancel();
		} catch (cause) {
			error = errorMessage(cause, 'Could not remove the phone alarm.');
		} finally {
			pending = false;
		}
	}
</script>

<form class="flex flex-col gap-6" onsubmit={save}>
	<ol class={['flex flex-col gap-5 text-sm', !inline && 'panel p-5']}>
		<li class="flex flex-col gap-1">
			<span class="font-medium">Install the ntfy app on your phone.</span>
			<span class="text-muted-foreground">
				<a
					class="underline"
					href="https://play.google.com/store/apps/details?id=io.heckel.ntfy"
					target="_blank"
					rel="noreferrer">Google Play</a
				>
				·
				<a
					class="underline"
					href="https://apps.apple.com/app/ntfy/id1625396347"
					target="_blank"
					rel="noreferrer">App Store</a
				>
			</span>
		</li>
		<li class="flex flex-col gap-2">
			<span class="font-medium">Subscribe to this alarm in ntfy.</span>
			<span class="text-muted-foreground">
				Scan this code with your phone’s camera and copy the name, or type it:
				<code class="select-all">{alarm.topic}</code>. Then tap + in ntfy, paste the name and tap
				Subscribe.
			</span>
			<img
				src={alarm.qr}
				alt={`Code with the name ${alarm.topic}`}
				class="size-40 rounded-lg border bg-white p-1"
			/>
			<span class="text-muted-foreground">
				Already on your phone?
				<!-- An ntfy:// link opens the app, not a page of this site. -->
				<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
				<a class="underline" href={alarm.link}>Open in ntfy</a>.
			</span>
		</li>
		<li class="flex flex-col gap-1">
			<span class="font-medium">Let the alarm ring through Do Not Disturb.</span>
			<span class="text-muted-foreground">
				On Android, open Settings › Apps › ntfy › Notifications, choose the max priority category
				and turn on Override Do Not Disturb. An iPhone shows the alarm, but stays silent while it is
				on silent mode.
			</span>
		</li>
		<li class="flex flex-col gap-1">
			<span class="font-medium">Let it ring like an alarm clock.</span>
			<span class="text-muted-foreground">
				On Android, open Settings in ntfy and turn on Keep alerting for highest priority. Under
				Channel settings › Max priority › Sound, pick an alarm tone. The alarm then rings until you
				swipe it away. An iPhone plays the sound once.
			</span>
		</li>
		<li class="flex flex-col items-start gap-2">
			<span class="font-medium">Send a test alarm.</span>
			<Button type="button" variant="outline" onclick={test} disabled={testing || pending}>
				{testing ? 'Sending…' : tested ? 'Send again' : 'Send a test alarm'}
			</Button>
			{#if tested || !alarm.saved}
				<label class="flex cursor-pointer items-center gap-3">
					<Checkbox bind:checked={received} disabled={pending} />
					<span>My phone rang</span>
				</label>
			{/if}
		</li>
	</ol>
	{#if !inline}
		<Field.Set>
			<Field.Legend>Which detectors ring the alarm?</Field.Legend>
			<Field.Group class="gap-1">
				{#each detectors as { meta }, index (meta.label)}
					<label
						for={`alarm-${index}`}
						class="-mx-2 flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2 hover:bg-accent"
					>
						<Checkbox
							id={`alarm-${index}`}
							checked={detectorLabels.includes(meta.label)}
							disabled={pending}
							onCheckedChange={(enabled) =>
								(detectorLabels = enabled
									? [...detectorLabels, meta.label]
									: detectorLabels.filter((label) => label !== meta.label))}
						/>
						<span class="text-sm font-medium">{meta.label}</span>
					</label>
				{:else}
					<Field.Description>
						You can save the alarm now and choose it when you add a detector.
					</Field.Description>
				{/each}
			</Field.Group>
		</Field.Set>
	{/if}
	{#if error}
		<Alert.Root variant="destructive">
			<Alert.Title>Phone alarm needs attention</Alert.Title>
			<Alert.Description>{error}</Alert.Description>
		</Alert.Root>
	{/if}
	<div class="flex flex-wrap gap-3">
		<Button type="submit" disabled={pending || !received}>
			{pending ? 'Saving…' : 'Save'}
		</Button>
		<Button type="button" variant="outline" onclick={onCancel} disabled={pending}>Cancel</Button>
	</div>
	{#if alarm.saved && !inline}
		<ConfirmRemove
			trigger="Remove the phone alarm…"
			title="Remove the phone alarm?"
			description="Detectors will stop ringing your phone. Telegram alerts stay as they are."
			keep="Keep alarm"
			confirm="Remove alarm"
			onConfirm={remove}
			disabled={pending}
		/>
	{/if}
</form>

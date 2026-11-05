<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import PageHeader from '$lib/components/page-header.svelte';
	import PhoneAlarmEditor from '$lib/components/phone-alarm-editor.svelte';
	const done = () => void goto(resolve('/notifications'));
</script>

<section class="page-narrow">
	<PageHeader
		back={{ href: resolve('/notifications'), label: 'Alerts' }}
		title="Phone alarm"
		description="A loud alarm on your phone for each detection, also at night. It comes next to the Telegram alert, through the free ntfy app."
	/>
	<PhoneAlarmEditor onSaved={done} onCancel={done} />
</section>

<script lang="ts">
	import { resolve } from '$app/paths';
	import PageHeader from '$lib/components/page-header.svelte';
	import SettingsEditor from './settings-editor.svelte';
</script>

<section class="page max-w-6xl">
	<PageHeader
		back={{ href: resolve('/settings'), label: 'Settings' }}
		title="Advanced"
		description="Everything the presets decide for you, as JSON: thresholds, prompts, delivery and the detection engine. Changes are checked before they are saved."
	/>
	<SettingsEditor />
</section>

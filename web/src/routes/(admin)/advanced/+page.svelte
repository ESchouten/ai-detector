<script lang="ts">
	import { getRuntime } from '$lib/remote/runtime.remote';
	import SettingsEditor from './settings-editor.svelte';
	const runtime = await getRuntime();
</script>

<svelte:head><title>Advanced · AI Detector</title></svelte:head>
<section class="settings-page max-w-6xl">
	<header class="flex flex-col gap-2">
		<h1 class="settings-heading">Advanced</h1>
		<p class="settings-description">
			Edit settings beyond the presets. JSON is checked against the application’s schema before
			saving.
		</p>
	</header>
	<SettingsEditor managed={runtime.managed} />
</section>

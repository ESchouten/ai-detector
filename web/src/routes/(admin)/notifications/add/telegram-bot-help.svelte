<script lang="ts">
	import { untrack } from 'svelte';
	import { Button } from '$lib/components/ui/button';
	let { initiallyOpen = true }: { initiallyOpen?: boolean } = $props();
	let open = $state(untrack(() => initiallyOpen));
	let copied = $state('');
	async function copyCommand() {
		try {
			await navigator.clipboard.writeText('/newbot');
			copied = 'Copied. Paste /newbot into BotFather.';
		} catch {
			copied = 'Type /newbot into BotFather.';
		}
	}
</script>

<details bind:open>
	<summary class="cursor-pointer text-sm">Create your Telegram bot</summary>
	<ol class="mt-3 flex list-decimal flex-col gap-2 pl-5 text-sm">
		<li>
			Open BotFather below, send <code>/newbot</code> and follow its instructions for a name and username.
		</li>
		<li>Copy the bot token from BotFather into AI Detector. Keep this token private.</li>
		<li>Choose Connect my bot below. We will give you a link to connect your phone.</li>
	</ol>
	<div class="mt-3 flex flex-wrap gap-2">
		<Button
			href="https://t.me/BotFather?text=%2Fnewbot"
			target="_blank"
			rel="noreferrer"
			variant="outline">Open BotFather</Button
		>
		<Button type="button" variant="outline" onclick={copyCommand}>Copy /newbot</Button>
	</div>
	{#if copied}<p class="mt-2 text-sm text-muted-foreground" role="status">{copied}</p>{/if}
</details>

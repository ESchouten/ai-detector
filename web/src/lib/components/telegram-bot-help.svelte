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

<details bind:open class="rounded-lg border bg-muted/40 px-4 py-3">
	<summary class="cursor-pointer text-sm font-medium">How to create your Telegram bot</summary>
	<ol class="mt-3 flex list-decimal flex-col gap-2 pl-5 text-sm leading-relaxed">
		<li>
			Open BotFather below, send <code class="rounded bg-muted px-1 py-0.5">/newbot</code> and follow
			its instructions for a name and username.
		</li>
		<li>Copy the bot token from BotFather into AI Detector. Keep this token private.</li>
		<li>Choose Connect Telegram below. Open the link or scan the code with your phone.</li>
	</ol>
	<div class="mt-3 flex flex-wrap gap-2">
		<Button
			href="https://t.me/BotFather?text=%2Fnewbot"
			target="_blank"
			rel="noreferrer"
			variant="outline"
			size="sm">Open BotFather</Button
		>
		<Button variant="outline" size="sm" onclick={copyCommand}>Copy /newbot</Button>
	</div>
	{#if copied}<p class="mt-2 text-sm text-muted-foreground" role="status">{copied}</p>{/if}
</details>

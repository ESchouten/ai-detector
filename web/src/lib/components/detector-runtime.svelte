<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { Button } from '$lib/components/ui/button';
	import { Badge } from '$lib/components/ui/badge';
	import * as Card from '$lib/components/ui/card';
	import * as Field from '$lib/components/ui/field';
	import * as NativeSelect from '$lib/components/ui/native-select';
	import { getRuntime, startDetector, stopDetector } from '$lib/remote/runtime.remote';
	import type { RuntimeMode } from '$lib/runtime';

	let { configured }: { configured: boolean } = $props();
	let runtime = $state(await getRuntime());
	let mode = $state<RuntimeMode>(untrack(() => runtime.mode));
	let requestError = $state('');
	const busy = $derived(['checking', 'starting', 'stopping'].includes(runtime.phase));

	onMount(() => {
		let active = true;
		let timer: ReturnType<typeof setTimeout>;
		async function refresh() {
			try {
				await getRuntime().refresh();
				runtime = await getRuntime();
				requestError = '';
			} catch {
				requestError =
					'Connection to the app was lost. Keep the application open and reload this page.';
			}
			if (active) timer = setTimeout(refresh, 2000);
		}
		timer = setTimeout(refresh, 2000);
		return () => {
			active = false;
			clearTimeout(timer);
		};
	});

	async function control(action: 'start' | 'stop') {
		requestError = '';
		try {
			runtime = action === 'start' ? await startDetector(mode) : await stopDetector();
			await getRuntime().refresh();
			runtime = await getRuntime();
		} catch {
			requestError =
				'The request could not be completed. Check that the application is still open.';
		}
	}
</script>

<Card.Root>
	<Card.Header>
		<Card.Title class="flex items-center justify-between gap-4"
			>Detection <Badge variant={runtime.phase === 'failed' ? 'destructive' : 'secondary'}
				>{runtime.phase}</Badge
			></Card.Title
		>
		<Card.Description aria-live="polite">{runtime.message}</Card.Description>
	</Card.Header>
	<Card.Content class="flex flex-col gap-4">
		{#if runtime.managed}
			<Field.Field>
				<Field.Label for="runtime-mode">Run detection</Field.Label>
				<NativeSelect.Root
					id="runtime-mode"
					bind:value={mode}
					disabled={busy || runtime.phase === 'running'}
				>
					<NativeSelect.Option value="auto"
						>Automatically choose for this computer</NativeSelect.Option
					>
					<NativeSelect.Option value="native">On this computer</NativeSelect.Option>
					<NativeSelect.Option value="docker">In Docker with an NVIDIA GPU</NativeSelect.Option>
				</NativeSelect.Root>
				<Field.Description
					>Automatic uses Docker for a detected NVIDIA GPU and the included application otherwise.</Field.Description
				>
			</Field.Field>
			{#if runtime.helpUrl}<Button
					href={runtime.helpUrl}
					target="_blank"
					rel="noreferrer"
					variant="outline">Open setup instructions</Button
				>{/if}
			{#if runtime.selected}<p class="text-sm text-muted-foreground">
					Selected: {runtime.selected === 'docker'
						? 'NVIDIA Docker'
						: 'native application with available system acceleration'}.
				</p>{/if}
		{:else}
			<Button
				href="https://github.com/ESchouten/ai-detector/releases"
				target="_blank"
				rel="noreferrer"
				variant="outline">Application downloads</Button
			>
		{/if}
		{#if requestError}<p role="alert" class="text-sm text-destructive">{requestError}</p>{/if}
		<details>
			<summary class="cursor-pointer text-sm text-muted-foreground"
				>Details for troubleshooting</summary
			>
			<p class="my-3 text-xs break-all text-muted-foreground">
				Settings and detections: {runtime.dataDirectory}
			</p>
			<pre
				class="max-h-64 overflow-auto rounded-md bg-muted p-3 text-xs break-all whitespace-pre-wrap">{runtime.logs ||
					'No detector output yet.'}</pre>
		</details>
	</Card.Content>
	{#if runtime.managed}
		<Card.Footer class="flex flex-wrap gap-3">
			{#if runtime.phase === 'running'}
				<Button variant="outline" onclick={() => control('stop')}>Stop detection</Button>
				<Button href="/detections">View detections</Button>
			{:else if runtime.phase === 'checking'}
				<Button variant="outline" onclick={() => control('stop')}>Cancel start</Button>
			{:else}
				<Button disabled={!configured || busy} onclick={() => control('start')}
					>{busy
						? 'Please wait…'
						: runtime.phase === 'failed'
							? 'Try again'
							: 'Start detection'}</Button
				>
			{/if}
		</Card.Footer>
	{/if}
</Card.Root>

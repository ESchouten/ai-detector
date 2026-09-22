<script lang="ts">
	import { errorMessage } from '$lib/remote-errors';
	import { onMount, untrack } from 'svelte';
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
	import { Badge } from '$lib/components/ui/badge';
	import * as Card from '$lib/components/ui/card';
	import * as Field from '$lib/components/ui/field';
	import * as NativeSelect from '$lib/components/ui/native-select';
	import { getRuntime, startDetector, stopDetector } from '$lib/remote/runtime.remote';
	import type { RuntimeMode } from '$lib/runtime';
	let { configured, compact = false }: { configured: boolean; compact?: boolean } = $props();
	let runtime = $state(await getRuntime());
	let mode = $state<RuntimeMode>(untrack(() => runtime.mode));
	let requestError = $state('');
	let connectionLost = $state(false);
	let lastCheckedAt = $state(Date.now());
	let now = $state(Date.now());
	const stale = $derived(connectionLost || now - lastCheckedAt > 10000);
	let controlling = $state(false);
	const busy = $derived(
		controlling || ['checking', 'starting', 'stopping'].includes(runtime.phase)
	);
	const labels = {
		idle: 'Paused',
		preparing: 'Preparing',
		connecting: 'Connecting cameras',
		monitoring: 'Monitoring',
		degraded: 'Needs attention',
		failed: 'Needs attention'
	};
	onMount(() => {
		let active = true;
		const clock = setInterval(() => (now = Date.now()), 1000);
		let timer: ReturnType<typeof setTimeout>;
		async function refresh() {
			try {
				await getRuntime().refresh();
				runtime = await getRuntime();
				connectionLost = false;
				lastCheckedAt = Date.now();
			} catch {
				connectionLost = true;
			}
			if (active) timer = setTimeout(refresh, 2000);
		}
		timer = setTimeout(refresh, 2000);
		return () => {
			active = false;
			clearTimeout(timer);
			clearInterval(clock);
		};
	});
	async function control(action: 'start' | 'stop') {
		requestError = '';
		controlling = true;
		try {
			runtime = action === 'start' ? await startDetector(mode) : await stopDetector();
			await getRuntime().refresh();
			runtime = await getRuntime();
			connectionLost = false;
			lastCheckedAt = Date.now();
		} catch (cause) {
			requestError = errorMessage(
				cause,
				'The request could not be completed. Check that AI Detector is still open.'
			);
		} finally {
			controlling = false;
		}
	}
</script>

<Card.Root>
	<Card.Header
		><Card.Title class="flex items-center justify-between gap-4"
			>Monitoring <Badge
				variant={stale || ['failed', 'degraded'].includes(runtime.readiness)
					? 'destructive'
					: 'secondary'}
				>{!stale && runtime.managed ? labels[runtime.readiness] : 'Status unavailable'}</Badge
			></Card.Title
		><Card.Description aria-live="polite"
			>{stale
				? `No recent status from the app. Last checked ${new Date(lastCheckedAt).toLocaleTimeString()}. Reopen AI Detector if it does not reconnect.`
				: (runtime.preparation ?? runtime.message)}</Card.Description
		></Card.Header
	>
	<Card.Content class="flex flex-col gap-4">
		{#if runtime.notice}<p class="text-sm text-muted-foreground">{runtime.notice}</p>{/if}
		{#if runtime.cameras.length && !compact}
			{#each runtime.cameras as camera (camera.id)}
				<div class="flex flex-col gap-1 text-sm">
					<p class="font-medium">
						{camera.label} · {stale
							? 'Status unavailable'
							: camera.error || camera.recordingError
								? 'Needs attention'
								: camera.state === 'monitoring'
									? 'Monitoring'
									: camera.state === 'paused'
										? 'Paused'
										: camera.state === 'receiving'
											? 'Picture received; preparing detection'
											: camera.state === 'connecting'
												? 'Connecting'
												: 'Needs attention'}
					</p>
					{#if camera.error}<p class="text-destructive">{camera.error}</p>{/if}
					{#if camera.recordingError}<p class="text-destructive">
							{camera.recordingError}
						</p>{/if}{#if camera.lastFrameAt}<p class="text-muted-foreground">
							Last picture: {new Date(camera.lastFrameAt).toLocaleTimeString()}
						</p>{/if}
				</div>
			{/each}
		{/if}
		{#if requestError}<p role="alert" class="text-sm text-destructive">{requestError}</p>{/if}
		{#if !compact}
			<p class="text-sm text-muted-foreground">
				Closing this browser tab leaves monitoring active. Pause monitoring is a separate choice and
				remains paused when you reopen the application.
			</p>
			<details>
				<summary class="cursor-pointer text-sm text-muted-foreground"
					>Advanced and troubleshooting</summary
				>
				<div class="mt-4 flex flex-col gap-4">
					{#if runtime.managed}<Field.Field
							><Field.Label for="runtime-mode">Detection engine</Field.Label><NativeSelect.Root
								id="runtime-mode"
								bind:value={mode}
								disabled={busy || runtime.phase === 'running'}
								><NativeSelect.Option value="auto"
									>Automatically choose a working engine</NativeSelect.Option
								><NativeSelect.Option value="native">Bundled application</NativeSelect.Option
								><NativeSelect.Option value="docker">Managed NVIDIA container</NativeSelect.Option
								></NativeSelect.Root
							></Field.Field
						>{/if}
					{#if runtime.helpUrl}<Button
							href={runtime.helpUrl}
							target="_blank"
							rel="noreferrer"
							variant="outline">Setup instructions</Button
						>{/if}
					<p class="text-xs break-all text-muted-foreground">
						Settings and recordings: {runtime.dataDirectory}
					</p>
					<pre
						class="max-h-64 overflow-auto rounded-md bg-muted p-3 text-xs break-all whitespace-pre-wrap">{runtime.logs ||
							'No diagnostic output yet.'}</pre>
				</div>
			</details>
		{/if}
	</Card.Content>
	{#if runtime.managed}<Card.Footer class="flex flex-wrap gap-3">
			{#if runtime.phase === 'running'}<Button
					variant="outline"
					disabled={stale || controlling}
					onclick={() => control('stop')}>Pause monitoring</Button
				>{:else if runtime.phase === 'checking'}<Button
					variant="outline"
					disabled={stale || controlling}
					onclick={() => control('stop')}>Cancel preparation</Button
				>{:else}<Button disabled={!configured || busy || stale} onclick={() => control('start')}
					>{busy
						? 'Please wait…'
						: runtime.phase === 'failed'
							? 'Try again'
							: 'Start monitoring'}</Button
				>{/if}
			{#if !compact}<Button href={resolve('/detections')} variant="outline">Open recordings</Button
				>{/if}
			{#if compact && ['failed', 'degraded'].includes(runtime.readiness)}
				<Button href={resolve('/setup')} variant="outline">View monitoring details</Button>
			{/if}
		</Card.Footer>{/if}
</Card.Root>

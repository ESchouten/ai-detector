<script lang="ts">
	import { onDestroy } from 'svelte';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Badge } from '$lib/components/ui/badge';
	import * as Field from '$lib/components/ui/field';
	import { getCameraConnection } from '$lib/remote/camera.remote';
	import type { DiscoveredCamera } from '$lib/cameras';
	import { connectCameraBatch, type BatchCamera } from '$lib/camera-batch';

	let {
		candidates,
		finding,
		discoveryMessage,
		onfind,
		queue = $bindable([]),
		connecting = $bindable(false),
		activeAddress,
		activeSaved,
		disabled,
		onchoose,
		onskip,
		onclose
	}: {
		candidates: DiscoveredCamera[];
		finding: boolean;
		discoveryMessage: string;
		onfind: () => Promise<void>;
		queue?: BatchCamera[];
		connecting?: boolean;
		activeAddress: string;
		activeSaved: boolean;
		disabled: boolean;
		onchoose: (camera: BatchCamera) => void;
		onskip: () => void;
		onclose: () => void;
	} = $props();
	let selected = $state<string[]>([]);
	let username = $state('');
	let password = $state('');
	let choosing = $state(true);
	let controller: AbortController | undefined;
	const locked = $derived(
		disabled || connecting || finding || Boolean(activeAddress && !activeSaved)
	);
	const failures = $derived(queue.filter((camera) => camera.state === 'failed').length);
	const labels = {
		waiting: 'Waiting',
		connecting: 'Connecting',
		ready: 'Ready to add',
		failed: 'Needs attention',
		saved: 'Saved',
		skipped: 'Skipped — not saved'
	};
	onDestroy(() => controller?.abort());
	async function connect() {
		const known = new Set(queue.map((camera) => camera.address));
		queue = [
			...queue,
			...candidates
				.filter((camera) => selected.includes(camera.address) && !known.has(camera.address))
				.map((camera) => ({ ...camera, state: 'waiting' as const }))
		];
		const operation = new AbortController();
		controller = operation;
		connecting = true;
		choosing = false;
		await connectCameraBatch(
			queue,
			{ username, password },
			getCameraConnection,
			(updated) => {
				queue = queue.map((camera) => (camera.address === updated.address ? updated : camera));
			},
			operation.signal
		);
		if (!operation.signal.aborted) connecting = false;
	}
</script>

<section class="flex max-w-4xl flex-col gap-5" aria-label="Set up several cameras">
	<header class="flex flex-col gap-2">
		<h2 class="font-medium">{queue.length ? 'Your camera queue' : 'Set up several cameras'}</h2>
		<p class="text-sm text-muted-foreground">
			Select cameras that use the same login, then preview and name each camera before saving.
		</p>
	</header>
	<div class="flex flex-col gap-5">
		{#if queue.length}<Button
				type="button"
				variant="outline"
				class="self-start"
				disabled={locked}
				onclick={() => (choosing = !choosing)}
				>{choosing ? 'Hide camera selection' : 'Add cameras or change login'}</Button
			>{/if}
		{#if choosing}
			<Button type="button" variant="outline" class="self-start" disabled={locked} onclick={onfind}
				>{finding ? 'Looking for cameras…' : 'Find cameras'}</Button
			>
			{#if discoveryMessage}<p role="status" class="text-sm text-muted-foreground">
					{discoveryMessage}
				</p>{/if}
			<Field.Set>
				<Field.Legend>Discovered cameras</Field.Legend>
				<Field.Group>
					{#each candidates as camera, index (camera.address)}
						<Field.Label for={`batch-camera-${index}`} class="cursor-pointer">
							<Field.Field orientation="horizontal">
								<Checkbox
									id={`batch-camera-${index}`}
									checked={selected.includes(camera.address)}
									disabled={locked || queue.some((item) => item.address === camera.address)}
									onCheckedChange={(checked) =>
										(selected = checked
											? [...selected, camera.address]
											: selected.filter((address) => address !== camera.address))}
								/>
								<Field.Content
									><Field.Title>{camera.name}</Field.Title><Field.Description class="break-all"
										>{camera.address}</Field.Description
									></Field.Content
								>
							</Field.Field>
						</Field.Label>
					{:else}<Field.Description
							>Choose Find cameras to search this network. You can return to single-camera setup to
							enter an address manually.</Field.Description
						>{/each}
				</Field.Group>
			</Field.Set>
			<Field.Group class="grid gap-4 sm:grid-cols-2">
				<Field.Field
					><Field.Label for="batch-username">Camera username</Field.Label><Input
						id="batch-username"
						bind:value={username}
						disabled={locked}
						autocomplete="off"
					/></Field.Field
				>
				<Field.Field
					><Field.Label for="batch-password">Camera password</Field.Label><Input
						id="batch-password"
						type="password"
						bind:value={password}
						disabled={locked}
						autocomplete="off"
					/></Field.Field
				>
			</Field.Group>
			<p class="text-sm text-muted-foreground">
				The login and unsaved queue stay only in this page. Keep it open until you have saved the
				cameras you want.
			</p>
			<Button
				type="button"
				variant="outline"
				disabled={locked ||
					(!failures &&
						!selected.some((address) => !queue.some((camera) => camera.address === address)))}
				onclick={connect}
				>{connecting
					? 'Connecting cameras…'
					: failures
						? 'Retry failed cameras and connect selected'
						: 'Connect selected cameras'}</Button
			>
		{/if}
		{#if connecting}<p role="status" class="text-sm text-muted-foreground">
				Connecting the selected cameras. Each successful connection will be ready to add below.
			</p>{/if}
		{#if queue.length}
			<p role="status" class="text-sm">
				{queue.filter((camera) => camera.state === 'saved').length} saved · {queue.filter(
					(camera) => camera.state === 'ready'
				).length} ready to add · {failures} need attention · {queue.filter(
					(camera) => camera.state === 'skipped'
				).length} skipped
			</p>
			<ul class="divide-y">
				{#each queue as camera (camera.address)}
					<li class="flex min-w-0 flex-wrap items-center justify-between gap-3 py-3">
						<div class="flex flex-wrap items-center gap-2">
							<span class="font-medium">{camera.name}</span><Badge
								variant={camera.state === 'failed' ? 'destructive' : 'secondary'}
								>{camera.address === activeAddress && !activeSaved
									? 'Setting up this camera'
									: labels[camera.state]}</Badge
							>
						</div>
						{#if camera.error}<p role="alert" class="text-sm text-destructive">
								{camera.error}
							</p>{/if}
						{#if camera.address === activeAddress && !activeSaved}<Button
								type="button"
								variant="outline"
								{disabled}
								onclick={onskip}>Skip this camera for now</Button
							>
						{:else if camera.state === 'ready' || camera.state === 'skipped'}<Button
								type="button"
								variant="outline"
								disabled={locked}
								class="h-auto whitespace-normal"
								onclick={() => onchoose(camera)}>Preview {camera.name}</Button
							>{/if}
					</li>
				{/each}
			</ul>
		{/if}
		{#if queue.some((camera) => camera.state === 'saved')}<p class="text-sm text-muted-foreground">
				Save your cameras here. Choose their detectors together in the next step.
			</p>{/if}
	</div>
	<div class="flex flex-col items-start gap-2">
		<p class="text-sm text-muted-foreground">
			Returning clears unsaved queue entries. Saved cameras remain available in Cameras.
		</p>
		<Button
			type="button"
			variant="outline"
			disabled={disabled || connecting || finding}
			onclick={onclose}>Return to single-camera setup</Button
		>
	</div>
</section>

<script lang="ts">
	import { enhance } from '$app/forms';
	import { invalidateAll } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { Fingerprint, RefreshCw, Trash2, TriangleAlert, X } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import { Badge } from '$lib/components/ui/badge';
	import { Input } from '$lib/components/ui/input';
	import DetectorRuntime from '$lib/components/detector-runtime.svelte';
	import { useRuntimeStatus } from '$lib/hooks/runtime-status.svelte';
	import { herdEmptyState } from '$lib/herd-status';
	import * as Dialog from '$lib/components/ui/dialog';
	import * as Empty from '$lib/components/ui/empty';
	import * as Field from '$lib/components/ui/field';
	import * as NativeSelect from '$lib/components/ui/native-select';
	import type { SubmitFunction } from '@sveltejs/kit';
	import type { PageData, ActionData } from './$types';

	let { data, form }: { data: PageData; form: ActionData } = $props();
	const monitor = useRuntimeStatus();
	const initialRuntime = monitor.query.current ?? (await monitor.query);
	const runtime = $derived(monitor.query.current ?? initialRuntime);
	const emptyState = $derived(herdEmptyState(data.identityConfigured, runtime, monitor.stale));
	let selectedPhoto = $state<string | null>(null);
	let selectedCow = $state<string | null>(null);
	let assignOpen = $state(false);
	let editOpen = $state(false);
	let choice = $state('');
	let label = $state('');
	let busy = $state(false);
	const review = $derived(data.catalog?.review ?? []);
	const identities = $derived(data.catalog?.identities ?? []);
	const photo = $derived(review.find((item) => item.id === selectedPhoto));
	const cow = $derived(identities.find((item) => item.id === selectedCow));
	const confirmedCows = $derived(identities.filter((item) => item.samples.length > 0).length);
	const message = $derived(form && 'message' in form ? form.message : null);

	$effect(() => {
		if (!data.catalog) {
			assignOpen = false;
			editOpen = false;
		}
	});

	function image(id: string) {
		return resolve(`/herd/images/${id}`);
	}

	function identify(item: NonNullable<PageData['catalog']>['review'][number]) {
		selectedPhoto = item.id;
		choice =
			confirmedCows >= 2 && identities.some((entry) => entry.id === item.identity.id)
				? item.identity.id!
				: '';
		label = '';
		form = null;
		assignOpen = true;
	}

	function edit(item: NonNullable<PageData['catalog']>['identities'][number]) {
		selectedCow = item.id;
		label = item.name;
		form = null;
		editOpen = true;
	}

	const submit: SubmitFunction = ({ formData }) => {
		busy = true;
		return async ({ result, update }) => {
			try {
				await update({ reset: false });
				if (result.type === 'success') {
					if (formData.get('operation') === 'assign') assignOpen = false;
					if (['rename', 'remove-cow'].includes(String(formData.get('operation'))))
						editOpen = false;
				}
			} finally {
				busy = false;
			}
		};
	};
</script>

<svelte:head><title>Herd · AI Detector</title></svelte:head>

<section class="settings-page max-w-6xl">
	<header class="flex flex-col gap-2">
		<div class="flex flex-wrap items-center justify-between gap-3">
			<div class="flex items-center gap-3">
				<h1 class="settings-heading">Herd</h1>
				<Badge variant="secondary">Experimental</Badge>
			</div>
			<Button variant="outline" onclick={() => invalidateAll()} disabled={busy}>
				<RefreshCw data-icon="inline-start" />{data.catalog ? 'Refresh photos' : 'Try again'}
			</Button>
		</div>
		<p class="settings-description">
			Name your cows and confirm clear photos. Suggested matches always need your confirmation.
		</p>
	</header>
	{#if data.identityConfigured}
		<DetectorRuntime configured compact />
	{/if}

	{#if message && !assignOpen && !editOpen}
		<p role="alert" class="text-sm text-destructive">{message}</p>
	{/if}
	{#if data.catalog?.unavailable}
		<p role="status" class="text-sm text-muted-foreground">
			{data.catalog.unavailable} photo{data.catalog.unavailable === 1 ? '' : 's'} could not be loaded.
			Other photos are still available.
		</p>
	{/if}

	{#if !data.catalog}
		<Empty.Root>
			<Empty.Header>
				<Empty.Media variant="icon"><TriangleAlert /></Empty.Media>
				<Empty.Title>Herd unavailable</Empty.Title>
				<Empty.Description>
					Your saved herd could not be read. No herd files have been changed. Open Logs for details.
				</Empty.Description>
			</Empty.Header>
			<Empty.Content>
				<Button variant="outline" href={resolve('/logs')}>Open Logs</Button>
				<p class="text-sm text-muted-foreground">
					Keep your existing files. A saved Settings backup can restore confirmed cows and photos
					through “Use existing setup” on a new installation.
				</p>
			</Empty.Content>
		</Empty.Root>
	{:else if !review.length && !identities.length}
		<Empty.Root>
			<Empty.Header>
				<Empty.Media variant="icon"><Fingerprint /></Empty.Media>
				<Empty.Title>{emptyState.title}</Empty.Title>
				<Empty.Description>{emptyState.description}</Empty.Description>
			</Empty.Header>
			{#if !data.identityConfigured}
				<Empty.Content>
					<Button href={resolve('/setup?step=detectors&add=detector')}>Set up cow identity</Button>
				</Empty.Content>
			{/if}
		</Empty.Root>
	{:else}
		{#if confirmedCows < 2}
			<p class="text-sm text-muted-foreground">
				Add examples for at least two cows to start suggesting matches.
			</p>
		{/if}
		<section class="space-y-4" aria-labelledby="review-heading">
			<h2 id="review-heading" class="text-lg font-semibold">
				Photos to review ({review.length})
			</h2>
			{#if review.length}
				<div class="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
					{#each review as item (item.id)}
						{@const suggestion = identities.find((entry) => entry.id === item.identity.id)}
						<div class="space-y-2">
							<div class="relative overflow-hidden rounded-lg bg-muted">
								<img
									src={image(item.image)}
									alt="Cow photographed by a camera"
									class="aspect-[4/3] w-full object-contain"
									loading="lazy"
								/>
								{#if suggestion && confirmedCows >= 2}
									<Badge
										class="absolute top-2 left-2 max-w-[calc(100%-1rem)] truncate"
										variant="secondary">Possible match: {suggestion.name}</Badge
									>
								{/if}
							</div>
							<div class="flex items-center gap-2">
								<Button
									variant="outline"
									class="flex-1"
									onclick={() => identify(item)}
									disabled={busy}>Identify cow</Button
								>
								<form method="POST" use:enhance={submit}>
									<input type="hidden" name="revision" value={data.catalog.revision} />
									<input type="hidden" name="photo" value={item.id} />
									<Button
										type="submit"
										name="operation"
										value="discard"
										variant="ghost"
										size="icon"
										aria-label="Discard photo"
										disabled={busy}><Trash2 /></Button
									>
								</form>
							</div>
						</div>
					{/each}
				</div>
			{:else}
				<p class="text-sm text-muted-foreground">
					All photos reviewed. More will appear while monitoring is running. Refresh to check.
				</p>
			{/if}
		</section>

		<section class="space-y-4" aria-labelledby="cows-heading">
			<h2 id="cows-heading" class="text-lg font-semibold">Your cows ({identities.length})</h2>
			{#if identities.length}
				<div class="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
					{#each identities as item (item.id)}
						<div>
							{#if item.samples.length}
								<img
									src={image(item.samples[0])}
									alt={`Confirmed example of ${item.name}`}
									class="aspect-[4/3] w-full rounded-lg bg-muted object-contain"
									loading="lazy"
								/>
							{:else}
								<div
									class="flex aspect-[4/3] items-center justify-center rounded-lg bg-muted text-sm text-muted-foreground"
								>
									No examples yet
								</div>
							{/if}
							<div class="flex items-baseline justify-between gap-3 py-2">
								<span class="truncate font-medium">{item.name}</span><span
									class="shrink-0 text-sm text-muted-foreground"
									>{item.samples.length} example{item.samples.length === 1 ? '' : 's'}</span
								>
							</div>
							<Button
								variant="outline"
								class="w-full"
								onclick={() => edit(item)}
								aria-label={`Edit ${item.name} and its examples`}
								disabled={busy}>Edit examples</Button
							>
						</div>
					{/each}
				</div>
			{:else}
				<p class="text-sm text-muted-foreground">Choose a photo above to name your first cow.</p>
			{/if}
		</section>
	{/if}
</section>

{#if data.catalog}
	<Dialog.Root bind:open={assignOpen}>
		<Dialog.Content class="max-h-[90dvh] overflow-y-auto sm:max-w-lg">
			<Dialog.Header
				><Dialog.Title>Who is this?</Dialog.Title><Dialog.Description
					>Only confirm a photo when you know the cow. Different clear views make better examples.</Dialog.Description
				></Dialog.Header
			>
			{#if photo}
				<img
					src={image(photo.image)}
					alt="Cow to identify"
					class="max-h-64 w-full rounded-lg bg-muted object-contain"
				/>
				<form method="POST" use:enhance={submit} class="space-y-5">
					<input type="hidden" name="operation" value="assign" />
					<input type="hidden" name="revision" value={data.catalog.revision} />
					<input type="hidden" name="photo" value={photo.id} />
					<Field.Group>
						<Field.Field>
							<Field.Label for="cow-choice">Cow</Field.Label>
							<NativeSelect.Root id="cow-choice" name="cow" bind:value={choice}>
								<NativeSelect.Option value="">New cow</NativeSelect.Option>
								{#each identities as item (item.id)}<NativeSelect.Option value={item.id}
										>{item.name}</NativeSelect.Option
									>{/each}
							</NativeSelect.Root>
						</Field.Field>
						{#if !choice}
							<Field.Field
								><Field.Label for="cow-name">Name or tag number</Field.Label><Input
									id="cow-name"
									name="name"
									bind:value={label}
									maxlength={80}
									required
									placeholder="For example, 142"
								/></Field.Field
							>
						{/if}
					</Field.Group>
					{#if message}<p role="alert" class="text-sm text-destructive">{message}</p>{/if}
					<Dialog.Footer
						><Button variant="outline" onclick={() => (assignOpen = false)}>Cancel</Button><Button
							type="submit"
							disabled={busy}>Confirm example</Button
						></Dialog.Footer
					>
				</form>
			{/if}
		</Dialog.Content>
	</Dialog.Root>

	<Dialog.Root bind:open={editOpen}>
		<Dialog.Content class="max-h-[90dvh] overflow-y-auto sm:max-w-lg">
			<Dialog.Header
				><Dialog.Title>{cow?.name ?? 'Cow examples'}</Dialog.Title><Dialog.Description
					>Keep clear, varied photos of the same cow. Removed examples return to review.</Dialog.Description
				></Dialog.Header
			>
			{#if cow}
				<form method="POST" use:enhance={submit} class="space-y-3">
					<input type="hidden" name="operation" value="rename" />
					<input type="hidden" name="revision" value={data.catalog.revision} />
					<input type="hidden" name="cow" value={cow.id} />
					<Field.Field
						><Field.Label for="edit-name">Name or tag number</Field.Label>
						<div class="flex gap-2">
							<Input id="edit-name" name="name" bind:value={label} maxlength={80} required /><Button
								type="submit"
								variant="outline"
								disabled={busy || label.trim() === cow.name}>Save name</Button
							>
						</div></Field.Field
					>
				</form>
				<div class="grid grid-cols-2 gap-3">
					{#each cow.samples as sample (sample)}
						<div class="relative overflow-hidden rounded-lg bg-muted">
							<img
								src={image(sample)}
								alt={`Confirmed example of ${cow.name}`}
								class="aspect-[4/3] w-full object-contain"
								loading="lazy"
							/>
							<form method="POST" use:enhance={submit} class="absolute top-1 right-1">
								<input type="hidden" name="revision" value={data.catalog.revision} />
								<input type="hidden" name="cow" value={cow.id} />
								<input type="hidden" name="photo" value={sample} />
								<Button
									type="submit"
									name="operation"
									value="remove-example"
									size="icon-sm"
									variant="secondary"
									aria-label="Remove example"
									disabled={busy}><X /></Button
								>
							</form>
						</div>
					{/each}
				</div>
				{#if !cow.samples.length}<p class="text-sm text-muted-foreground">
						Add a photo from the review list to recognize this cow.
					</p>{/if}
				{#if message}<p role="alert" class="text-sm text-destructive">{message}</p>{/if}
				<Dialog.Footer class="sm:justify-between">
					<form method="POST" use:enhance={submit}>
						<input type="hidden" name="revision" value={data.catalog.revision} />
						<input type="hidden" name="cow" value={cow.id} />
						<Button
							type="submit"
							name="operation"
							value="remove-cow"
							variant="ghost"
							class="text-destructive"
							disabled={busy}><Trash2 data-icon="inline-start" />Remove cow</Button
						>
					</form>
					<Button variant="outline" onclick={() => (editOpen = false)}>Done</Button>
				</Dialog.Footer>
			{/if}
		</Dialog.Content>
	</Dialog.Root>
{/if}

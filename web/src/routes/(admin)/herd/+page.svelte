<script lang="ts">
	import { enhance } from '$app/forms';
	import { invalidateAll } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { tick } from 'svelte';
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
	import * as Pagination from '$lib/components/ui/pagination';
	import * as Tabs from '$lib/components/ui/tabs';
	import type { SubmitFunction } from '@sveltejs/kit';
	import type { PageData, ActionData } from './$types';

	let { data, form }: { data: PageData; form: ActionData } = $props();
	const monitor = useRuntimeStatus();
	const initialRuntime = monitor.query.current ?? (await monitor.query);
	const runtime = $derived(monitor.query.current ?? initialRuntime);
	const emptyState = $derived(herdEmptyState(data.identityConfigured, runtime, monitor.stale));
	let selectedPhoto = $state<string | null>(null);
	let selectedCow = $state<string | null>(null);
	let dialog = $state<'identify' | 'examples' | null>(null);
	let previousCow = $state<string | null>(null);
	let cowChoice = $state<HTMLSelectElement | null>(null);
	let choice = $state('');
	let label = $state('');
	let busy = $state(false);
	const pageSize = 12;
	let reviewPage = $state(1);
	let cowsPage = $state(1);
	const review = $derived(data.catalog?.review ?? []);
	const identities = $derived(data.catalog?.identities ?? []);
	const photo = $derived(review.find((item) => item.id === selectedPhoto));
	const cow = $derived(identities.find((item) => item.id === selectedCow));
	const previous = $derived(identities.find((item) => item.id === previousCow));
	const target = $derived(identities.find((item) => item.id === choice));
	const reference = $derived(target?.samples.find((sample) => sample !== selectedPhoto));
	const confirmedCows = $derived(identities.filter((item) => item.samples.length > 0).length);
	const message = $derived(form && 'message' in form ? form.message : null);

	$effect(() => {
		reviewPage = Math.min(reviewPage, Math.max(1, Math.ceil(review.length / pageSize)));
		cowsPage = Math.min(cowsPage, Math.max(1, Math.ceil(identities.length / pageSize)));
		if (!data.catalog) {
			dialog = null;
		}
	});

	function image(id: string) {
		return resolve(`/herd/images/${id}`);
	}

	function capturedAt(value: string) {
		return new Date(value).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
	}

	function identify(item: NonNullable<PageData['catalog']>['review'][number]) {
		selectedPhoto = item.id;
		previousCow = null;
		choice =
			confirmedCows >= 2 && identities.some((entry) => entry.id === item.identity.id)
				? item.identity.id!
				: '';
		label = '';
		form = null;
		dialog = 'identify';
	}

	async function reassign(sample: string, owner: string) {
		selectedPhoto = sample;
		previousCow = owner;
		choice = owner;
		label = '';
		form = null;
		dialog = 'identify';
		await tick();
		cowChoice?.focus();
	}

	function edit(item: NonNullable<PageData['catalog']>['identities'][number]) {
		selectedCow = item.id;
		label = item.name;
		form = null;
		dialog = 'examples';
	}

	const submit: SubmitFunction = ({ formData }) => {
		busy = true;
		return async ({ result, update }) => {
			try {
				await update({ reset: false });
				if (result.type === 'success') {
					if (['assign', 'rename', 'remove-cow'].includes(String(formData.get('operation'))))
						dialog = null;
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

	{#if message && !dialog}
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
		<Tabs.Root value="review" class="gap-4">
			<Tabs.List aria-label="Herd views">
				<Tabs.Trigger value="review">Photos to review ({review.length})</Tabs.Trigger>
				<Tabs.Trigger value="cows">Your cows ({identities.length})</Tabs.Trigger>
			</Tabs.List>
			<Tabs.Content value="review" class="flex flex-col gap-4">
				{#if review.length}
					<div class="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
						{#each review.slice((reviewPage - 1) * pageSize, reviewPage * pageSize) as item (item.id)}
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
								<p class="flex flex-wrap justify-between gap-x-2 text-xs text-muted-foreground">
									<span>{data.cameras[item.source] ?? 'Saved camera'}</span>
									<time datetime={item.captured_at}>{capturedAt(item.captured_at)}</time>
								</p>
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
					{#if review.length > pageSize}
						<Pagination.Root
							count={review.length}
							perPage={pageSize}
							bind:page={reviewPage}
							aria-label="Review photos pages"
						>
							<Pagination.Content>
								<Pagination.Item><Pagination.Previous /></Pagination.Item>
								<li class="px-3 text-sm text-muted-foreground" aria-live="polite">
									{reviewPage} / {Math.ceil(review.length / pageSize)}
								</li>
								<Pagination.Item><Pagination.Next /></Pagination.Item>
							</Pagination.Content>
						</Pagination.Root>
					{/if}
				{:else}
					<p class="text-sm text-muted-foreground">
						All photos reviewed. More will appear while monitoring is running. Refresh to check.
					</p>
				{/if}
			</Tabs.Content>

			<Tabs.Content value="cows" class="flex flex-col gap-4">
				{#if identities.length}
					<div class="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
						{#each identities.slice((cowsPage - 1) * pageSize, cowsPage * pageSize) as item (item.id)}
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
					{#if identities.length > pageSize}
						<Pagination.Root
							count={identities.length}
							perPage={pageSize}
							bind:page={cowsPage}
							aria-label="Your cows pages"
						>
							<Pagination.Content>
								<Pagination.Item><Pagination.Previous /></Pagination.Item>
								<li class="px-3 text-sm text-muted-foreground" aria-live="polite">
									{cowsPage} / {Math.ceil(identities.length / pageSize)}
								</li>
								<Pagination.Item><Pagination.Next /></Pagination.Item>
							</Pagination.Content>
						</Pagination.Root>
					{/if}
				{:else}
					<p class="text-sm text-muted-foreground">
						Choose a photo in “Photos to review” to name your first cow.
					</p>
				{/if}
			</Tabs.Content>
		</Tabs.Root>
	{/if}
</section>

{#if data.catalog}
	<Dialog.Root
		open={dialog !== null}
		onOpenChange={(open) => {
			if (!open) dialog = null;
		}}
	>
		<Dialog.Content class="max-h-[90dvh] overflow-y-auto sm:max-w-xl">
			{#if dialog === 'identify'}
				<Dialog.Header>
					<Dialog.Title>Who is this?</Dialog.Title>
					<Dialog.Description>
						{#if previous}
							Currently confirmed as {previous.name}. Choose the correct cow to move this example.
						{:else}
							Only confirm a photo when you know the cow. Different clear views make better
							examples.
						{/if}
					</Dialog.Description>
				</Dialog.Header>
				{#if selectedPhoto}
					<div class={reference ? 'grid grid-cols-2 gap-3' : 'flex flex-col'}>
						<figure class="flex min-w-0 flex-col gap-2">
							<img
								src={image(selectedPhoto)}
								alt="Cow to identify"
								class="aspect-[4/3] max-h-64 w-full rounded-lg bg-muted object-contain"
							/>
							<figcaption class="text-sm text-muted-foreground">This photo</figcaption>
						</figure>
						{#if reference && target}
							<figure class="flex min-w-0 flex-col gap-2">
								<img
									src={image(reference)}
									alt={`Confirmed example of ${target.name}`}
									class="aspect-[4/3] max-h-64 w-full rounded-lg bg-muted object-contain"
								/>
								<figcaption class="text-sm break-words text-muted-foreground">
									Confirmed example: {target.name}
								</figcaption>
							</figure>
						{/if}
					</div>
					{#if photo}
						<p class="flex flex-wrap justify-between gap-x-2 text-sm text-muted-foreground">
							<span>{data.cameras[photo.source] ?? 'Saved camera'}</span>
							<time datetime={photo.captured_at}>{capturedAt(photo.captured_at)}</time>
						</p>
					{/if}
					<form method="POST" use:enhance={submit} class="flex flex-col gap-5">
						<input type="hidden" name="operation" value="assign" />
						<input type="hidden" name="revision" value={data.catalog.revision} />
						<input type="hidden" name="photo" value={selectedPhoto} />
						<input type="hidden" name="previousCow" value={previousCow ?? ''} />
						<Field.Group>
							<Field.Field>
								<Field.Label for="cow-choice">Cow</Field.Label>
								<NativeSelect.Root
									id="cow-choice"
									name="cow"
									bind:value={choice}
									bind:ref={cowChoice}
								>
									<NativeSelect.Option value="">New cow</NativeSelect.Option>
									{#each identities as item (item.id)}
										<NativeSelect.Option value={item.id}>{item.name}</NativeSelect.Option>
									{/each}
								</NativeSelect.Root>
							</Field.Field>
							{#if !choice}
								<Field.Field>
									<Field.Label for="cow-name">Name or tag number</Field.Label>
									<Input
										id="cow-name"
										name="name"
										bind:value={label}
										maxlength={80}
										required
										placeholder="For example, 142"
									/>
								</Field.Field>
							{/if}
						</Field.Group>
						{#if message}<p role="alert" class="text-sm text-destructive">{message}</p>{/if}
						<Dialog.Footer>
							<Button variant="outline" onclick={() => (dialog = null)} disabled={busy}
								>Cancel</Button
							>
							<Button type="submit" disabled={busy || (!!previousCow && choice === previousCow)}>
								{previousCow ? 'Move example' : 'Confirm example'}
							</Button>
						</Dialog.Footer>
					</form>
				{/if}
			{:else}
				<Dialog.Header>
					<Dialog.Title>{cow?.name ?? 'Cow examples'}</Dialog.Title>
					<Dialog.Description>
						Keep clear, varied photos of the same cow. Change the cow for a wrong match, or remove
						an unclear example.
					</Dialog.Description>
				</Dialog.Header>
				{#if cow}
					<form method="POST" use:enhance={submit} class="flex flex-col gap-3">
						<input type="hidden" name="operation" value="rename" />
						<input type="hidden" name="revision" value={data.catalog.revision} />
						<input type="hidden" name="cow" value={cow.id} />
						<Field.Field>
							<Field.Label for="edit-name">Name or tag number</Field.Label>
							<div class="flex gap-2">
								<Input id="edit-name" name="name" bind:value={label} maxlength={80} required />
								<Button type="submit" variant="outline" disabled={busy || label.trim() === cow.name}
									>Save name</Button
								>
							</div>
						</Field.Field>
					</form>
					<div class="grid grid-cols-2 gap-3">
						{#each cow.samples as sample (sample)}
							<div class="flex min-w-0 flex-col gap-2">
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
								<Button
									variant="outline"
									size="sm"
									onclick={() => reassign(sample, cow.id)}
									disabled={busy}>Change cow</Button
								>
							</div>
						{/each}
					</div>
					{#if !cow.samples.length}
						<p class="text-sm text-muted-foreground">
							Add a photo from the review list to recognize this cow.
						</p>
					{/if}
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
						<Button variant="outline" onclick={() => (dialog = null)} disabled={busy}>Done</Button>
					</Dialog.Footer>
				{/if}
			{/if}
		</Dialog.Content>
	</Dialog.Root>
{/if}

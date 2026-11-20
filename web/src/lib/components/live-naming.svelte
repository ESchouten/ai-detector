<script lang="ts">
	import { invalidateAll } from '$app/navigation';
	import { Button } from '$lib/components/ui/button';
	import * as Dialog from '$lib/components/ui/dialog';
	import { Input } from '$lib/components/ui/input';
	import { identityLabel, type DetectionBox } from '$lib/live-preview';
	import { errorMessage } from '$lib/remote-calls';
	import { getSighting, nameSighting } from '$lib/remote/identities.remote';
	import SightingPicture from './sighting-picture.svelte';

	let {
		box = $bindable(),
		names
	}: {
		/** The live box to name; the dialog is open while there is one. */
		box: DetectionBox | null;
		/** The id of the list of names already given, for suggestions while typing, where there is one. */
		names?: string;
	} = $props();
	const identity = $derived(box?.identity ?? null);
	let name = $state('');
	let saving = $state(false);
	let message = $state('');
	// Asked whether it is the one it looks most like, until a person says no.
	let declined = $state(false);
	const guess = $derived(
		identity?.name === null && !declined ? identity.candidates.at(0)?.name : undefined
	);

	$effect(() => {
		void identity;
		name = '';
		message = '';
		declined = false;
	});

	async function save(given: string) {
		if (!identity) return;
		saving = true;
		message = '';
		try {
			await nameSighting({ sighting: identity.sighting, name: given });
			box = null;
			await invalidateAll();
		} catch (cause) {
			message = errorMessage(cause, 'Could not save the name. Try again.');
		} finally {
			saving = false;
		}
	}
</script>

<Dialog.Root
	open={box !== null}
	onOpenChange={(open) => {
		if (!open) box = null;
	}}
>
	<Dialog.Content class="sm:max-w-lg">
		{#if box && identity}
			{@const shown = identityLabel(identity)}
			<Dialog.Header>
				<Dialog.Title>
					{#if guess}Is this {guess}?{:else}Who is this?{/if}
				</Dialog.Title>
				<Dialog.Description>
					{#if identity.name !== null}
						Shown as {identity.name}. Enter another name or number if that is wrong.
					{:else if shown}
						Looks most like {identity.candidates[0].name}, but not enough to be sure.
					{:else}
						Give it a name or number; the camera then recognises it.
					{/if}
				</Dialog.Description>
			</Dialog.Header>
			{#await getSighting(identity.sighting) then sighting}
				{#if sighting}
					<ul class="grid grid-cols-4 gap-2">
						{#each { length: sighting.crops }, index (index)}
							<li class="relative aspect-square overflow-hidden rounded-lg bg-media">
								<SightingPicture {sighting} {index} />
							</li>
						{/each}
					</ul>
				{:else}
					<p class="text-sm text-muted-foreground">
						Its pictures were removed. Wait for the box to show it again.
					</p>
				{/if}
			{/await}
			{#if guess}
				<div class="flex flex-col gap-2">
					<div class="flex gap-2">
						<Button disabled={saving} onclick={() => save(guess)}>
							{saving ? 'Saving…' : 'Yes'}
						</Button>
						<Button variant="outline" disabled={saving} onclick={() => (declined = true)}>
							No
						</Button>
					</div>
					{#if message}<p role="alert" class="text-sm text-danger-foreground">{message}</p>{/if}
				</div>
			{:else}
				<form
					class="flex flex-col gap-2"
					onsubmit={(event) => {
						event.preventDefault();
						void save(name);
					}}
				>
					<label for="live-name" class="text-sm font-medium">Name or number</label>
					<div class="flex gap-2">
						<Input
							id="live-name"
							bind:value={name}
							list={names}
							maxlength={40}
							autocomplete="off"
							required
							class="max-w-48"
						/>
						<Button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
					</div>
					{#if identity.candidates.length > (declined ? 1 : 0)}
						<div class="flex flex-wrap items-center gap-2">
							<span class="text-xs text-muted-foreground">Looks most like</span>
							{#each identity.candidates.slice(declined ? 1 : 0) as candidate (candidate.name)}
								<Button
									type="button"
									size="sm"
									variant="outline"
									onclick={() => (name = candidate.name)}>{candidate.name}</Button
								>
							{/each}
						</div>
					{/if}
					{#if message}<p role="alert" class="text-sm text-danger-foreground">{message}</p>{/if}
				</form>
			{/if}
		{/if}
	</Dialog.Content>
</Dialog.Root>

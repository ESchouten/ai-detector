<script lang="ts">
	import { enhance } from '$app/forms';
	import { SvelteSet } from 'svelte/reactivity';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { plural, recentMoment } from '$lib/format';
	import type { SightingGroup } from '$lib/individuals';
	import SightingPicture from '$lib/components/sighting-picture.svelte';
	import TagPictures from '$lib/components/tag-pictures.svelte';

	let {
		group,
		names
	}: {
		group: SightingGroup;
		/** The id of the list of names already given, for suggestions while typing. */
		names: string;
	} = $props();
	// Pictures people took out of the group because they show a different individual.
	const leftOut = new SvelteSet<string>();
	const kept = $derived(group.ids.filter((id) => !leftOut.has(id)));
	const field = $derived(`name-${group.ids[0]}`);
	let name = $state('');
	let saving = $state(false);
	// Asked whether it is the number on the tag in one of its pictures or else the one it looks
	// most like, until a person says no.
	let declined = $state(false);
	const tagged = $derived(
		group.shown.find((sighting) => sighting.tag && !leftOut.has(sighting.id))
	);
	const asked = $derived(tagged?.tag?.number ?? group.suggestions.at(0));
	const guess = $derived(declined ? undefined : asked);
	const others = $derived(group.suggestions.filter((suggestion) => suggestion !== asked));

	function toggle(id: string) {
		if (leftOut.has(id)) leftOut.delete(id);
		else leftOut.add(id);
	}
</script>

<article class="panel flex flex-col gap-4 p-4">
	<div class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
		<h3 class="text-sm font-semibold">
			{plural(group.ids.length, ['# sighting', '# sightings'])}
		</h3>
		<p class="text-xs text-muted-foreground">Last seen {recentMoment(group.shown[0].seen)}</p>
	</div>
	<ul class="grid grid-cols-[repeat(auto-fill,minmax(6.5rem,1fr))] gap-2">
		{#each group.shown as sighting (sighting.id)}
			{@const out = leftOut.has(sighting.id)}
			<li>
				<button
					type="button"
					aria-pressed={out}
					aria-label={out ? 'Left out: a different one' : 'Leave this picture out'}
					onclick={() => toggle(sighting.id)}
					class="relative block aspect-square w-full overflow-hidden rounded-lg bg-media outline-none focus-visible:ring-[3px] focus-visible:ring-ring/60"
				>
					<SightingPicture
						{sighting}
						loading="lazy"
						class={['transition-opacity', out && 'opacity-30']}
					/>
					{#if out}
						<span
							class="absolute inset-x-1 bottom-1 rounded bg-black/65 px-1 py-0.5 text-xs text-white"
						>
							Left out
						</span>
					{/if}
				</button>
			</li>
		{/each}
	</ul>
	<!-- Separate pieces, so each is a whole sentence to translate; the gap supplies the space. -->
	<p class="flex flex-wrap gap-x-1 text-xs text-muted-foreground">
		{#if group.ids.length > group.shown.length}
			<span>
				{plural(group.ids.length - group.shown.length, [
					'# more sighting looks like these.',
					'# more sightings look like these.'
				])}
			</span>
		{/if}
		<span>Tap a picture of a different one to leave it out.</span>
	</p>
	<form
		method="POST"
		action="?/name"
		class="flex flex-col gap-2"
		use:enhance={() => {
			saving = true;
			return async ({ result, update }) => {
				await update();
				if (result.type === 'success') {
					leftOut.clear();
					name = '';
					declined = false;
				}
				saving = false;
			};
		}}
	>
		{#each kept as id (id)}
			<input type="hidden" name="sighting" value={id} />
		{/each}
		{#if guess}
			<div class="flex flex-wrap items-center gap-3">
				{#if tagged?.tag}
					<TagPictures sighting={tagged} tag={tagged.tag} />
				{:else if group.reference}
					<div class="relative size-24 shrink-0 overflow-hidden rounded-lg bg-media">
						<SightingPicture sighting={group.reference} loading="lazy" />
					</div>
				{/if}
				<div class="flex flex-col gap-2">
					<p class="text-sm font-medium">Is this {guess}?</p>
					{#if tagged}
						<p class="text-xs text-muted-foreground">This number was read from its tag.</p>
					{:else if group.reference}
						<p class="text-xs text-muted-foreground">This picture was named {guess} before.</p>
					{/if}
					<div class="flex gap-2">
						<!-- A Yes to a likeness is the detector's own guess; a number read from a tag is not. -->
						<Button
							type="submit"
							name={tagged ? 'name' : 'confirm'}
							value={guess}
							disabled={saving || !kept.length}
						>
							{saving ? 'Saving…' : 'Yes'}
						</Button>
						<Button type="button" variant="outline" onclick={() => (declined = true)}>No</Button>
					</div>
				</div>
			</div>
		{:else}
			<label for={field} class="text-sm font-medium">Name or number</label>
			<div class="flex gap-2">
				<Input
					id={field}
					name="name"
					bind:value={name}
					list={names}
					maxlength={40}
					autocomplete="off"
					required
					class="max-w-48"
				/>
				<Button type="submit" disabled={saving || !kept.length}>
					{saving ? 'Saving…' : 'Save'}
				</Button>
			</div>
			{#if others.length}
				<div class="flex flex-wrap items-center gap-2">
					<span class="text-xs text-muted-foreground">Looks most like</span>
					{#each others as suggestion (suggestion)}
						<Button type="button" size="sm" variant="outline" onclick={() => (name = suggestion)}>
							{suggestion}
						</Button>
					{/each}
				</div>
			{/if}
		{/if}
	</form>
</article>

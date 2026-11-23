<script lang="ts">
	import { onTopMark, type Detection } from '$lib/detections';
	import { identityLabel, type Identity } from '$lib/live-preview';
	import { getSighting } from '$lib/remote/identities.remote';
	import LiveNaming from './live-naming.svelte';
	import SightingPicture from './sighting-picture.svelte';

	// Who a recording shows, each with a picture and a tap to say who it is.
	let { individuals }: { individuals: NonNullable<Detection['individuals']> } = $props();
	const sightings = $derived(
		await Promise.all(individuals.map((individual) => getSighting(individual.sighting)))
	);
	// Its pictures go when a person removes a sighting; the recording then only keeps the name. A
	// name given since the recording counts, and a tag's number is asked of one without a name.
	const shown = $derived(
		individuals.flatMap((individual, index) => {
			const sighting = sightings[index];
			if (!sighting) return [];
			const identity: Identity = {
				sighting: sighting.id,
				name: sighting.name ?? individual.name,
				candidates: individual.candidates,
				tag: sighting.tag?.number ?? null
			};
			return [{ sighting, identity, mark: onTopMark(individual) }];
		})
	);
	let naming = $state<Identity | null>(null);
</script>

{#if shown.length}
	<ul class="flex flex-wrap gap-2 px-5 pt-4">
		{#each shown as { sighting, identity, mark } (sighting.id)}
			<li>
				<button
					type="button"
					class="flex cursor-pointer items-center gap-2 rounded-lg border bg-background p-1 pr-3 text-sm font-medium hover:bg-accent"
					onclick={() => (naming = identity)}
				>
					<span class="relative size-12 overflow-hidden rounded-md bg-media">
						<SightingPicture {sighting} loading="lazy" />
					</span>
					{mark}{identityLabel(identity) ?? 'Who is this?'}
				</button>
			</li>
		{/each}
	</ul>
{/if}
<LiveNaming bind:identity={naming} />

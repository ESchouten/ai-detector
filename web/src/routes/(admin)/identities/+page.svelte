<script lang="ts">
	import { enhance } from '$app/forms';
	import { resolve } from '$app/paths';
	import { X } from '@lucide/svelte';
	import * as Alert from '$lib/components/ui/alert';
	import PageHeader from '$lib/components/page-header.svelte';
	import { plural } from '$lib/format';
	import SightingGroup from './sighting-group.svelte';

	let { data, form } = $props();
	const overview = $derived(data.overview);
</script>

<section class="page-narrow">
	<PageHeader
		back={{ href: resolve('/settings'), label: 'Settings' }}
		title="Identities"
		description="Each group holds sightings that look alike. Give it a name or number once; alerts then name the identities they recognise."
	/>

	{#if form?.message}
		<Alert.Root variant="destructive">
			<Alert.Title>Could not save the name</Alert.Title>
			<Alert.Description>{form.message}</Alert.Description>
		</Alert.Root>
	{/if}
	{#if overview.named.length && overview.namedDays < 2}
		<Alert.Root>
			<Alert.Title>Name sightings from one more day</Alert.Title>
			<Alert.Description>
				Alerts only suggest names until named sightings come from at least two days. From then on
				they name the identities they are sure of.
			</Alert.Description>
		</Alert.Root>
	{/if}

	<datalist id="identity-names">
		{#each overview.named as identity (identity.name)}
			<option value={identity.name}></option>
		{/each}
	</datalist>

	<section class="flex flex-col gap-3" aria-labelledby="identities-unnamed">
		<h2 id="identities-unnamed" class="text-base font-semibold">To name</h2>
		{#if overview.groups.length}
			{#each overview.groups as group (group.ids[0])}
				<SightingGroup {group} names="identity-names" />
			{/each}
			{#if overview.moreGroups}
				<p class="text-sm text-muted-foreground">
					{plural(overview.moreGroups, [
						'# more group follows once these are named.',
						'# more groups follow once these are named.'
					])}
				</p>
			{/if}
		{:else}
			<p class="text-sm text-muted-foreground">
				Nothing to name. New sightings appear here when a detector with tracking records an
				individual.
			</p>
		{/if}
	</section>

	<section class="flex flex-col gap-3" aria-labelledby="identities-named">
		<h2 id="identities-named" class="text-base font-semibold">Named identities</h2>
		{#if overview.named.length}
			<ul class="panel divide-y">
				{#each overview.named as identity (identity.name)}
					<li>
						<details class="group">
							<summary
								class="flex cursor-pointer list-none items-center justify-between gap-4 px-4 py-3.5"
							>
								<span class="text-sm font-medium">{identity.name}</span>
								<span class="text-sm text-muted-foreground">
									{plural(identity.ids.length, ['# sighting', '# sightings'])}
								</span>
							</summary>
							<ul class="flex flex-wrap gap-2 px-4 pb-4">
								{#each identity.shown as sighting (sighting.id)}
									<li class="relative size-24 overflow-hidden rounded-lg bg-media">
										<img
											src={resolve(`/identities/${sighting.id}/crop-1.jpg`)}
											alt=""
											loading="lazy"
											decoding="async"
											class="size-full object-contain"
										/>
										<form
											method="POST"
											action="?/unname"
											use:enhance
											class="absolute top-1 right-1"
										>
											<input type="hidden" name="sighting" value={sighting.id} />
											<button
												type="submit"
												aria-label={`Not ${identity.name}: remove the name from this picture`}
												class="flex size-7 items-center justify-center rounded-full bg-black/65 text-white outline-none hover:bg-black/80 focus-visible:ring-[3px] focus-visible:ring-ring/60"
											>
												<X class="size-4" aria-hidden="true" />
											</button>
										</form>
									</li>
								{/each}
							</ul>
						</details>
					</li>
				{/each}
			</ul>
		{:else}
			<p class="text-sm text-muted-foreground">No identities named yet.</p>
		{/if}
	</section>
</section>

<script lang="ts">
	import { ChevronRight, ExternalLink } from '@lucide/svelte';
	import type { NavItem } from '$lib/navigation';
	// A list of destinations with room to say what each one is for.
	let { items }: { items: NavItem[] } = $props();
</script>

<ul class="panel divide-y overflow-hidden">
	{#each items as item (item.href)}
		{@const external = item.href.startsWith('http')}
		<li>
			<a
				href={item.href}
				target={external ? '_blank' : undefined}
				rel={external ? 'noreferrer' : undefined}
				class="group flex items-center gap-4 px-4 py-3.5 transition-colors outline-none hover:bg-accent/60 focus-visible:bg-accent"
			>
				<span
					class="flex size-9 shrink-0 items-center justify-center rounded-lg bg-secondary text-secondary-foreground"
				>
					<item.icon class="size-[1.125rem]" aria-hidden="true" />
				</span>
				<span class="flex min-w-0 flex-1 flex-col">
					<span class="text-sm font-medium">{item.title}</span>
					{#if item.description}
						<span class="text-sm text-muted-foreground">{item.description}</span>
					{/if}
				</span>
				{#if external}
					<ExternalLink class="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
				{:else}
					<ChevronRight
						class="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5"
						aria-hidden="true"
					/>
				{/if}
			</a>
		</li>
	{/each}
</ul>

<script lang="ts">
	import { page } from '$app/state';
	import * as Sidebar from '$lib/components/ui/sidebar/index.js';
	import type { WithoutChildren } from '$lib/utils';
	import type { ComponentProps } from 'svelte';
	import { isActive, isSettingsArea, type NavItem } from '$lib/navigation';

	let {
		title,
		items,
		...restProps
	}: {
		title?: string;
		items: NavItem[];
	} & WithoutChildren<ComponentProps<typeof Sidebar.Group>> = $props();
</script>

<Sidebar.Group {...restProps}>
	{#if title}<Sidebar.GroupLabel>{title}</Sidebar.GroupLabel>{/if}
	<Sidebar.Menu>
		{#each items as item (item.href)}
			{@const active =
				item.area === 'settings'
					? isSettingsArea(page.url.pathname)
					: isActive(item, page.url.pathname)}
			{@const external = item.href.startsWith('http')}
			<Sidebar.MenuItem>
				<Sidebar.MenuButton isActive={active} class="h-9 gap-2.5 px-2.5">
					{#snippet child({ props })}
						<a
							href={item.href}
							{...props}
							aria-current={active ? 'page' : undefined}
							target={external ? '_blank' : undefined}
							rel={external ? 'noreferrer' : undefined}
						>
							<item.icon />
							<span>{item.title}</span>
						</a>
					{/snippet}
				</Sidebar.MenuButton>
			</Sidebar.MenuItem>
		{/each}
	</Sidebar.Menu>
</Sidebar.Group>

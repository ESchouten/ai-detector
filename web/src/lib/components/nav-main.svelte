<script lang="ts">
	import { page } from '$app/state';
	import * as Sidebar from '$lib/components/ui/sidebar/index.js';
	import type { WithoutChildren } from '$lib/utils';
	import type { ComponentProps } from 'svelte';
	import type { NavItem } from './types';

	let {
		title,
		items,
		size = 'default',
		...restProps
	}: {
		title: string;
		items: NavItem[];
		size?: 'lg' | 'default' | 'sm';
	} & WithoutChildren<ComponentProps<typeof Sidebar.Group>> = $props();

	function isActive(item: NavItem): boolean {
		const path = new URL(item.url, page.url).pathname;
		return (
			page.url.pathname === path ||
			page.url.pathname.startsWith(`${path}/`) ||
			(item.title === 'Settings' && page.route.id?.startsWith('/(admin)/detectors') === true)
		);
	}
</script>

<Sidebar.Group {...restProps}>
	<Sidebar.GroupLabel>{title}</Sidebar.GroupLabel>
	<Sidebar.Menu>
		{#each items as item (item.title)}
			<Sidebar.MenuItem>
				<Sidebar.MenuButton {size} isActive={isActive(item)}>
					{#snippet child({ props })}
						<a href={item.url} {...props} aria-current={isActive(item) ? 'page' : undefined}>
							<item.icon />
							<span>{item.title}</span>
						</a>
					{/snippet}
				</Sidebar.MenuButton>
			</Sidebar.MenuItem>
		{/each}
	</Sidebar.Menu>
</Sidebar.Group>

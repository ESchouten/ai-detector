<script lang="ts">
	import { resolve } from '$app/paths';
	import NavUser from './nav-user.svelte';
	import * as Sidebar from '$lib/components/ui/sidebar/index.js';
	import CCTV from '@lucide/svelte/icons/cctv';
	import type { ComponentProps } from 'svelte';
	import NavMain from './nav-main.svelte';
	import type { NavMenu, NavItem } from './types';

	let {
		title,
		subtitle,
		user,
		menu,
		secondaryMenu,
		ref = $bindable(null),
		...restProps
	}: {
		title: string;
		subtitle: string;
		menu: NavMenu[];
		secondaryMenu?: NavMenu[];
		user?: {
			name?: string;
			email?: string;
			avatar?: string;
			items: NavItem[];
			logout: () => void;
		};
	} & ComponentProps<typeof Sidebar.Root> = $props();
</script>

<Sidebar.Root bind:ref variant="inset" {...restProps}>
	<Sidebar.Header>
		<Sidebar.Menu>
			<Sidebar.MenuItem>
				<Sidebar.MenuButton size="lg">
					{#snippet child({ props })}
						<a href={resolve('/')} {...props}>
							<div
								class="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground"
							>
								<CCTV class="size-4" />
							</div>
							<div class="grid flex-1 text-start text-sm leading-tight">
								<span class="truncate font-medium">{title}</span>
								<span class="truncate text-xs">{subtitle}</span>
							</div>
						</a>
					{/snippet}
				</Sidebar.MenuButton>
			</Sidebar.MenuItem>
		</Sidebar.Menu>
	</Sidebar.Header>
	<Sidebar.Content>
		{#each menu as item (item.title)}
			<NavMain title={item.title} items={item.items} />
		{/each}
		{#each secondaryMenu || [] as item (item.title)}
			<NavMain title={item.title} items={item.items} size="sm" class="mt-auto" />
		{/each}
	</Sidebar.Content>
	{#if user}
		<Sidebar.Footer>
			<NavUser {user} items={user.items} logout={user.logout} />
		</Sidebar.Footer>
	{/if}
</Sidebar.Root>

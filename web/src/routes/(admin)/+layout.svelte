<script lang="ts">
	import { resolve } from '$app/paths';
	import type { NavMenu } from '$lib/components/types';
	import AppSidebar from '$lib/components/app-sidebar.svelte';
	import * as Breadcrumb from '$lib/components/ui/breadcrumb/index.js';
	import { Separator } from '$lib/components/ui/separator/index.js';
	import * as Sidebar from '$lib/components/ui/sidebar/index.js';
	import { version } from '$lib/version';
	import TVIcon from '@lucide/svelte/icons/tv';
	import CameraIcon from '@lucide/svelte/icons/camera';
	import BellIcon from '@lucide/svelte/icons/bell';
	import { page } from '$app/state';
	import GithubIcon from '@lucide/svelte/icons/github';
	import CircleCheckIcon from '@lucide/svelte/icons/circle-check';

	let { children } = $props();

	const menu: NavMenu[] = [
		{
			title: 'Overview',
			items: [
				{
					title: 'Recordings',
					url: resolve('/detections'),
					icon: CameraIcon
				},
				{
					title: 'Cameras',
					url: resolve('/streams'),
					icon: TVIcon
				}
			]
		},
		{
			title: 'Manage',
			items: [
				{
					title: 'Settings',
					url: resolve('/setup'),
					icon: CircleCheckIcon
				},
				{
					title: 'Alerts',
					url: resolve('/notifications'),
					icon: BellIcon
				}
			]
		}
	];
	const pageNames: Record<string, string> = {
		detections: 'Recordings',
		streams: 'Cameras',
		notifications: 'Alerts',
		setup: 'Settings',
		detectors: 'Advanced monitoring',
		add: 'Settings'
	};

	const secondaryMenu: NavMenu[] = [
		{
			title: 'Support',
			items: [
				{
					title: 'Github',
					url: 'https://github.com/ESchouten/ai-detector',
					icon: GithubIcon
				}
			]
		}
	];
</script>

<Sidebar.Provider>
	<AppSidebar title="AI Detector" subtitle={version} {menu} {secondaryMenu} />
	<Sidebar.Inset>
		<header class="flex h-16 shrink-0 items-center gap-2">
			<div class="flex items-center gap-2 px-4">
				<Sidebar.Trigger class="-ms-1" />
				<Separator orientation="vertical" class="me-2 data-[orientation=vertical]:h-4" />
				<Breadcrumb.Root>
					<Breadcrumb.List>
						<Breadcrumb.Item class="hidden md:block">
							<Breadcrumb.Link href="/">AI Detector</Breadcrumb.Link>
						</Breadcrumb.Item>
						{#each page.url.pathname.split('/').filter(Boolean) as path, index (`${index}:${path}`)}
							<Breadcrumb.Separator class="hidden md:block" />
							<Breadcrumb.Item>
								<Breadcrumb.Page>{pageNames[path] ?? path}</Breadcrumb.Page>
							</Breadcrumb.Item>
						{/each}
					</Breadcrumb.List>
				</Breadcrumb.Root>
			</div>
		</header>
		<div class="flex flex-1 flex-col gap-4 p-4 pt-0">
			{@render children()}
		</div>
	</Sidebar.Inset>
</Sidebar.Provider>

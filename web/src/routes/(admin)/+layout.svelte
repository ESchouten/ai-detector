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
	import SparklesIcon from '@lucide/svelte/icons/sparkles';
	import { page } from '$app/state';
	import GithubIcon from '@lucide/svelte/icons/github';
	import SettingsIcon from '@lucide/svelte/icons/settings';
	import CodeIcon from '@lucide/svelte/icons/code';
	import LogsIcon from '@lucide/svelte/icons/logs';
	import { createRuntimeStatus, provideRuntimeStatus } from '$lib/hooks/runtime-status.svelte';

	let { children } = $props();
	provideRuntimeStatus(createRuntimeStatus());

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
					icon: SettingsIcon
				},
				{
					title: 'Alerts',
					url: resolve('/notifications'),
					icon: BellIcon
				},
				{
					title: 'Validator',
					url: resolve('/validator'),
					icon: SparklesIcon
				},
				{ title: 'Advanced', url: resolve('/advanced'), icon: CodeIcon }
			]
		}
	];
	const pageNames: Record<string, string> = {
		detections: 'Recordings',
		streams: 'Cameras',
		notifications: 'Alerts',
		validator: 'Validator',
		advanced: 'Advanced',
		setup: 'Settings',
		logs: 'Logs',
		devices: 'Connected devices',
		storage: 'Storage',
		detectors: 'Detectors',
		add: 'Settings'
	};

	const secondaryMenu: NavMenu[] = [
		{
			title: 'Support',
			items: [
				{
					title: 'Logs',
					url: resolve('/logs'),
					icon: LogsIcon
				},
				{
					title: 'GitHub',
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
			<div class="flex items-center gap-2 px-4 md:px-6 lg:px-8">
				<Sidebar.Trigger class="-ms-1" />
				<Separator orientation="vertical" class="me-2 data-[orientation=vertical]:h-4" />
				<Breadcrumb.Root>
					<Breadcrumb.List>
						<Breadcrumb.Item class="hidden md:block">
							<Breadcrumb.Link href="/">AI Detector</Breadcrumb.Link>
						</Breadcrumb.Item>
						{#each page.url.pathname.split('/').filter(Boolean) as path, index (`${index}:${path}`)}
							<Breadcrumb.Separator class={index === 0 ? 'hidden md:block' : ''} />
							<Breadcrumb.Item>
								<Breadcrumb.Page>{pageNames[path] ?? path}</Breadcrumb.Page>
							</Breadcrumb.Item>
						{/each}
					</Breadcrumb.List>
				</Breadcrumb.Root>
			</div>
		</header>
		<div class="flex min-w-0 flex-1 flex-col gap-4 p-4 pt-0 md:px-6 md:pb-6 lg:px-8 lg:pb-8">
			{@render children()}
		</div>
	</Sidebar.Inset>
</Sidebar.Provider>

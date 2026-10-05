<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import * as Sidebar from '$lib/components/ui/sidebar/index.js';
	import { ChevronRight } from '@lucide/svelte';
	import GithubIcon from '@lucide/svelte/icons/github';
	import BrandMark from './brand-mark.svelte';
	import NavMain from './nav-main.svelte';
	import StatusDot from './status-dot.svelte';
	import ThemeToggle from './theme-toggle.svelte';
	import type { MonitoringSummary } from '$lib/monitoring';
	import { mainNavigation, settingsHome, REPOSITORY_URL } from '$lib/navigation';

	let { summary, version }: { summary: MonitoringSummary; version: string } = $props();
	const statusPage = resolve('/status');
</script>

<Sidebar.Root
	collapsible="none"
	class="sticky top-0 hidden h-svh shrink-0 border-r border-sidebar-border md:flex"
>
	<Sidebar.Header class="gap-3 p-3">
		<a
			href={resolve('/')}
			class="flex items-center gap-2.5 rounded-md px-1 py-1 outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring"
		>
			<BrandMark />
			<span class="text-[0.9375rem] font-semibold tracking-tight">AI Detector</span>
		</a>
		<a
			href={statusPage}
			aria-current={page.url.pathname === statusPage ? 'page' : undefined}
			class="group flex items-center gap-3 rounded-lg border border-sidebar-border bg-background px-3 py-2.5 outline-none hover:bg-sidebar-accent focus-visible:ring-2 focus-visible:ring-sidebar-ring aria-[current=page]:bg-sidebar-accent"
		>
			<StatusDot tone={summary.tone} />
			<span class="flex min-w-0 flex-1 flex-col">
				<span class="truncate text-sm leading-tight font-medium" role="status">{summary.label}</span
				>
				<span class="truncate text-xs text-muted-foreground"
					>{summary.tone === 'ok' ? summary.detail : 'View monitoring status'}</span
				>
			</span>
			<ChevronRight
				class="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5"
				aria-hidden="true"
			/>
		</a>
	</Sidebar.Header>
	<Sidebar.Content>
		<NavMain items={[...mainNavigation(), settingsHome()]} />
		<NavMain
			class="mt-auto"
			items={[{ title: 'Help on GitHub', href: REPOSITORY_URL, icon: GithubIcon }]}
		/>
	</Sidebar.Content>
	<Sidebar.Footer class="flex-row items-center justify-between border-t border-sidebar-border px-4">
		<span class="text-xs text-muted-foreground">Version {version}</span>
		<ThemeToggle />
	</Sidebar.Footer>
</Sidebar.Root>

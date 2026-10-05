<script lang="ts">
	import { page } from '$app/state';
	import { isActive, isSettingsArea, mainNavigation, settingsHome } from '$lib/navigation';
	const items = $derived([...mainNavigation(), settingsHome()]);
</script>

<nav
	aria-label="Main"
	class="fixed inset-x-0 bottom-0 z-30 border-t bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
>
	<ul class="mx-auto grid max-w-lg grid-cols-4">
		{#each items as item (item.href)}
			{@const active =
				item.area === 'settings'
					? isSettingsArea(page.url.pathname)
					: isActive(item, page.url.pathname)}
			<li>
				<a
					href={item.href}
					aria-current={active ? 'page' : undefined}
					class="flex h-16 flex-col items-center justify-center gap-1 text-[0.6875rem] font-medium text-muted-foreground outline-none focus-visible:bg-accent aria-[current=page]:text-primary"
				>
					<item.icon class="size-[1.375rem]" aria-hidden="true" />
					{item.title}
				</a>
			</li>
		{/each}
	</ul>
</nav>

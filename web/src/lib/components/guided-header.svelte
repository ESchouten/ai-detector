<script lang="ts">
	import { resolve } from '$app/paths';
	import { LifeBuoy } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import * as DropdownMenu from '$lib/components/ui/dropdown-menu';
	import BrandMark from './brand-mark.svelte';
	import LanguageMenu from './language-menu.svelte';
	import ThemeToggle from './theme-toggle.svelte';
	import { REPOSITORY_URL } from '$lib/navigation';
</script>

<header class="flex h-14 items-center justify-between gap-3 border-b px-4 md:px-8">
	<div class="flex items-center gap-2.5">
		<BrandMark class="size-7 rounded-md" />
		<span class="text-[0.9375rem] font-semibold tracking-tight">AI Detector</span>
	</div>
	<div class="flex items-center gap-1">
		<LanguageMenu />
		<ThemeToggle />
		<DropdownMenu.Root>
			<DropdownMenu.Trigger>
				{#snippet child({ props })}
					<Button {...props} variant="ghost" size="sm">
						<LifeBuoy data-icon="inline-start" aria-hidden="true" />Help
					</Button>
				{/snippet}
			</DropdownMenu.Trigger>
			<DropdownMenu.Content align="end">
				<DropdownMenu.Group>
					<DropdownMenu.Item>
						{#snippet child({ props })}<a {...props} href={resolve('/devices')}
								>Open on a phone or other computer</a
							>{/snippet}
					</DropdownMenu.Item>
					<DropdownMenu.Item>
						{#snippet child({ props })}<a {...props} href={resolve('/logs')}>Logs and diagnostics</a
							>{/snippet}
					</DropdownMenu.Item>
					<DropdownMenu.Item>
						{#snippet child({ props })}<a
								{...props}
								href={REPOSITORY_URL}
								target="_blank"
								rel="noreferrer">Help on GitHub</a
							>{/snippet}
					</DropdownMenu.Item>
				</DropdownMenu.Group>
			</DropdownMenu.Content>
		</DropdownMenu.Root>
	</div>
</header>

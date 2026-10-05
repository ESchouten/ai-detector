<script lang="ts">
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import { Activity, Archive, Monitor, Moon, Sun } from '@lucide/svelte';
	import GithubIcon from '@lucide/svelte/icons/github';
	import { setMode, userPrefersMode } from 'mode-watcher';
	import { Button } from '$lib/components/ui/button';
	import HomeScreenGuide from '$lib/components/home-screen-guide.svelte';
	import LanguageMenu from '$lib/components/language-menu.svelte';
	import LinkRows from '$lib/components/link-rows.svelte';
	import PageHeader from '$lib/components/page-header.svelte';
	import SettingsBackup from '$lib/components/settings-backup.svelte';
	import { deviceLacksHomeScreenIcon } from '$lib/home-screen';
	import { logsNavigation, settingsNavigation, REPOSITORY_URL } from '$lib/navigation';
	import { version } from '$lib/version';

	const themes = [
		{ value: 'light', label: 'Light', icon: Sun },
		{ value: 'dark', label: 'Dark', icon: Moon },
		{ value: 'system', label: 'Automatic', icon: Monitor }
	] as const;
	// Only a phone or tablet that does not have the application on its home screen yet.
	let homeScreen = $state(false);
	let homeScreenGuide = $state<HomeScreenGuide>();
	onMount(() => {
		homeScreen = deviceLacksHomeScreenIcon();
	});
</script>

<svelte:head><title>Settings · AI Detector</title></svelte:head>
<section class="page-narrow">
	<PageHeader title="Settings" />

	<LinkRows items={settingsNavigation()} />

	<section class="flex flex-col gap-3" aria-labelledby="settings-general">
		<h2 id="settings-general" class="text-base font-semibold">This installation</h2>
		<div class="panel divide-y">
			<div class="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 px-4 py-3.5">
				<div class="flex min-w-0 flex-col">
					<p class="text-sm font-medium">Language</p>
					<p class="text-sm text-muted-foreground">
						Used on every device and for replies in Telegram.
					</p>
				</div>
				<LanguageMenu variant="outline" />
			</div>
			<div class="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 px-4 py-3.5">
				<div class="flex min-w-0 flex-col">
					<p class="text-sm font-medium">Appearance</p>
					<p class="text-sm text-muted-foreground">Automatic follows this device.</p>
				</div>
				<div role="group" aria-label="Appearance" class="flex rounded-lg border bg-muted/60 p-0.5">
					{#each themes as theme (theme.value)}
						<button
							type="button"
							aria-pressed={userPrefersMode.current === theme.value}
							onclick={() => setMode(theme.value)}
							class="flex h-8 items-center gap-1.5 rounded-md px-2.5 text-sm font-medium text-muted-foreground outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 aria-pressed:bg-background aria-pressed:text-foreground aria-pressed:shadow-xs"
						>
							<theme.icon class="size-4" aria-hidden="true" />{theme.label}
						</button>
					{/each}
				</div>
			</div>
			{#if homeScreen}
				<div class="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 px-4 py-3.5">
					<div class="flex min-w-0 flex-col">
						<p class="text-sm font-medium">Home screen</p>
						<p class="text-sm text-muted-foreground">
							Open AI Detector with one tap from this device’s home screen.
						</p>
					</div>
					<Button variant="outline" onclick={() => homeScreenGuide?.show()}>Show me how</Button>
				</div>
				<HomeScreenGuide bind:this={homeScreenGuide} />
			{/if}
			<div class="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 px-4 py-3.5">
				<div class="flex min-w-0 items-center gap-4">
					<span
						class="flex size-9 shrink-0 items-center justify-center rounded-lg bg-secondary text-secondary-foreground"
					>
						<Archive class="size-[1.125rem]" aria-hidden="true" />
					</span>
					<div class="flex min-w-0 flex-col">
						<p class="text-sm font-medium">Back up settings</p>
						<p class="text-sm text-muted-foreground">
							Download cameras, detectors and alert settings to keep them safe.
						</p>
					</div>
				</div>
				<SettingsBackup />
			</div>
		</div>
	</section>

	<section class="flex flex-col gap-3" aria-labelledby="settings-support">
		<h2 id="settings-support" class="text-base font-semibold">Support</h2>
		<LinkRows
			items={[
				{
					title: 'Monitoring status',
					href: resolve('/status'),
					icon: Activity,
					description: 'What each camera is doing right now.'
				},
				logsNavigation(),
				{
					title: 'Help on GitHub',
					href: REPOSITORY_URL,
					icon: GithubIcon,
					description: 'Guides, questions and bug reports.'
				}
			]}
		/>
		<p class="text-xs text-muted-foreground">AI Detector version {version}</p>
	</section>
</section>

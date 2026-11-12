<script lang="ts">
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import { Activity, Archive, Download, Monitor, Moon, Sun } from '@lucide/svelte';
	import LifeBuoyIcon from '@lucide/svelte/icons/life-buoy';
	import { setMode, userPrefersMode } from 'mode-watcher';
	import { Button, buttonVariants } from '$lib/components/ui/button';
	import * as Dialog from '$lib/components/ui/dialog';
	import HomeScreenGuide from '$lib/components/home-screen-guide.svelte';
	import LanguageMenu from '$lib/components/language-menu.svelte';
	import LinkRows from '$lib/components/link-rows.svelte';
	import PageHeader from '$lib/components/page-header.svelte';
	import SegmentedControl from '$lib/components/segmented-control.svelte';
	import { deviceHoldsOnlyShortcut, deviceLacksHomeScreenIcon } from '$lib/home-screen';
	import { logsNavigation, settingsNavigation, REPOSITORY_URL } from '$lib/navigation';
	import { version } from '$lib/version';

	let { data } = $props();

	const themes = [
		{ value: 'light', label: 'Light', icon: Sun },
		{ value: 'dark', label: 'Dark', icon: Moon },
		{ value: 'system', label: 'Automatic', icon: Monitor }
	] as const;
	// Only a phone or tablet that does not have the application on its home screen yet.
	let homeScreen = $state(false);
	let shortcutOnly = $state(false);
	let homeScreenGuide = $state<HomeScreenGuide>();
	onMount(() => {
		homeScreen = deviceLacksHomeScreenIcon();
		shortcutOnly = deviceHoldsOnlyShortcut();
	});
</script>

<section class="page-narrow">
	<PageHeader title="Settings" />

	<LinkRows items={settingsNavigation({ individuals: data.individuals })} />

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
				<SegmentedControl
					label="Appearance"
					options={themes}
					value={userPrefersMode.current}
					onChange={setMode}
				/>
			</div>
			{#if homeScreen && shortcutOnly}
				<div class="flex flex-col px-4 py-3.5">
					<p class="text-sm font-medium">Home screen shortcut</p>
					<p class="text-sm text-muted-foreground">
						Open your browser’s menu (⋮) and choose “Add to Home screen”. The shortcut opens AI
						Detector in the browser.
					</p>
				</div>
			{:else if homeScreen}
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
				<Dialog.Root>
					<Dialog.Trigger class={buttonVariants({ variant: 'outline', size: 'sm' })}>
						<Download data-icon="inline-start" aria-hidden="true" />Back up
					</Dialog.Trigger>
					<Dialog.Content>
						<Dialog.Header>
							<Dialog.Title>Back up settings</Dialog.Title>
							<Dialog.Description>
								Save your cameras, detectors and alert settings in one ZIP.
							</Dialog.Description>
						</Dialog.Header>
						<p class="text-sm">Includes saved passwords and tokens. Keep this backup private.</p>
						<p class="text-sm text-muted-foreground">
							Recordings and model files are not included. To restore, extract the ZIP and choose
							Use existing setup in a new installation.
						</p>
						<Dialog.Footer>
							<Button href={resolve('/settings/backup')} download data-sveltekit-reload>
								<Download data-icon="inline-start" aria-hidden="true" />Download backup
							</Button>
						</Dialog.Footer>
					</Dialog.Content>
				</Dialog.Root>
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
					icon: LifeBuoyIcon,
					description: 'Guides, questions and bug reports.'
				}
			]}
		/>
		<p class="text-xs text-muted-foreground">AI Detector version {version}</p>
	</section>
</section>

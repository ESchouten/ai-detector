<script lang="ts">
	import { Check, Languages } from '@lucide/svelte';
	import { toast } from 'svelte-sonner';
	import { Button, type ButtonVariant } from '$lib/components/ui/button';
	import * as DropdownMenu from '$lib/components/ui/dropdown-menu';
	import { LANGUAGE_NAMES, LOCALES, language, type Locale } from '$lib/locales';
	import { errorMessage } from '$lib/remote-errors';
	import { setLanguage } from '$lib/remote/language.remote';

	let { variant = 'ghost' }: { variant?: ButtonVariant } = $props();
	const current = $derived(language() as Locale);
	let pending = $state(false);

	async function choose(next: Locale) {
		if (next === current) return;
		pending = true;
		try {
			await setLanguage(next);
			// Text written by the server changes too, so load every page afresh.
			location.reload();
		} catch (cause) {
			pending = false;
			toast.error(errorMessage(cause, 'The language could not be changed. Try again.'));
		}
	}
</script>

<DropdownMenu.Root>
	<DropdownMenu.Trigger>
		{#snippet child({ props })}
			<Button {...props} {variant} size="sm" disabled={pending} aria-label="Language">
				<Languages data-icon="inline-start" aria-hidden="true" />
				<!-- Language names stay in their own language so anyone can find theirs. -->
				<span lang={current}>{LANGUAGE_NAMES[current]}</span>
			</Button>
		{/snippet}
	</DropdownMenu.Trigger>
	<DropdownMenu.Content align="end">
		<DropdownMenu.Group>
			{#each LOCALES as locale (locale)}
				<DropdownMenu.Item onSelect={() => choose(locale)} lang={locale}>
					<span class="min-w-0 flex-1">{LANGUAGE_NAMES[locale]}</span>
					{#if locale === current}<Check aria-hidden="true" />{/if}
				</DropdownMenu.Item>
			{/each}
		</DropdownMenu.Group>
	</DropdownMenu.Content>
</DropdownMenu.Root>

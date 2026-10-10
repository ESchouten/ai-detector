<script lang="ts">
	import { Eye, EyeOff } from '@lucide/svelte';
	import type { HTMLInputAttributes } from 'svelte/elements';
	import * as InputGroup from '$lib/components/ui/input-group';

	// Passwords, keys and stream URLs with logins stay hidden until someone asks to see them.
	let {
		value = $bindable(''),
		name,
		...rest
	}: Omit<HTMLInputAttributes, 'type' | 'value' | 'files'> & {
		value?: string;
		/** What is hidden, for the show and hide button: "API key", "stream URL". */
		name: string;
	} = $props();
	let shown = $state(false);
</script>

<InputGroup.Root>
	<InputGroup.Input
		type={shown ? 'text' : 'password'}
		bind:value
		autocomplete="off"
		spellcheck={false}
		{...rest}
	/>
	<InputGroup.Addon align="inline-end">
		<InputGroup.Button
			size="icon-sm"
			aria-label={shown ? `Hide ${name}` : `Show ${name}`}
			title={shown ? `Hide ${name}` : `Show ${name}`}
			onclick={() => (shown = !shown)}
		>
			{#if shown}<EyeOff />{:else}<Eye />{/if}
		</InputGroup.Button>
	</InputGroup.Addon>
</InputGroup.Root>

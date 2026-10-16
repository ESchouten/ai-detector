<script lang="ts">
	import type { Snippet } from 'svelte';
	import { Input } from '$lib/components/ui/input';
	import * as Field from '$lib/components/ui/field';
	import SecretInput from './secret-input.svelte';

	// How a camera is reached: its whole stream URL, or the login of a camera found on the network.
	let {
		manual,
		streamUri = $bindable(''),
		username = $bindable(''),
		password = $bindable(''),
		disabled,
		oninput,
		children
	}: {
		manual: boolean;
		streamUri?: string;
		username?: string;
		password?: string;
		disabled: boolean;
		oninput?: () => void;
		/** Said after the login's description. */
		children?: Snippet;
	} = $props();
</script>

{#if manual}
	<Field.Field>
		<Field.Label for="camera-stream">RTSP URL</Field.Label>
		<SecretInput
			id="camera-stream"
			name="stream URL"
			bind:value={streamUri}
			{oninput}
			{disabled}
			placeholder="rtsp://192.168.1.50/stream"
			aria-describedby="camera-stream-help"
		/>
		<Field.Description id="camera-stream-help">
			Paste the full stream URL, including the username and password if the camera needs them.
		</Field.Description>
	</Field.Field>
{:else}
	<Field.Group>
		<Field.Group class="grid gap-4 sm:grid-cols-2">
			<Field.Field>
				<Field.Label for="camera-username">Camera username</Field.Label>
				<Input id="camera-username" bind:value={username} {oninput} {disabled} autocomplete="off" />
			</Field.Field>
			<Field.Field>
				<Field.Label for="camera-password">Camera password</Field.Label>
				<Input
					id="camera-password"
					type="password"
					bind:value={password}
					{oninput}
					{disabled}
					autocomplete="off"
				/>
			</Field.Field>
		</Field.Group>
		<Field.Description>
			The camera’s own login, which may differ from its phone app.
			{@render children?.()}
		</Field.Description>
	</Field.Group>
{/if}

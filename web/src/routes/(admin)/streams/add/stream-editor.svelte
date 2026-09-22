<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { untrack } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import * as Field from '$lib/components/ui/field';
	import * as Alert from '$lib/components/ui/alert';
	import Stream from '../stream.svelte';
	import { deleteStream, saveStream } from '$lib/remote/stream.remote';

	let {
		originalSource,
		initialLabel,
		setupMode
	}: { originalSource: string; initialLabel: string; setupMode: boolean } = $props();
	let source = $state(untrack(() => originalSource));
	let label = $state(untrack(() => initialLabel));
	let preview = $state(untrack(() => originalSource));
	let previewVersion = $state(0);
	let pending = $state(false);
	let error = $state('');

	async function remove() {
		pending = true;
		error = '';
		try {
			await deleteStream({ source: originalSource });
			await goto(resolve('/streams'));
		} catch (cause) {
			error = cause instanceof Error ? cause.message : 'Could not delete this source.';
		} finally {
			pending = false;
		}
	}
</script>

<section class="flex flex-col gap-6">
	<header class="flex flex-col gap-1">
		<h1 class="text-2xl font-semibold tracking-tight">
			{originalSource ? 'Edit stream' : setupMode ? 'Setup: Add stream' : 'Add stream'}
		</h1>
		<p class="text-sm text-muted-foreground">Add a camera source and test its preview.</p>
	</header>
	<div class="grid min-w-0 gap-6 lg:grid-cols-2">
		<form
			class="flex w-full max-w-lg flex-col gap-6"
			{...saveStream.enhance(async ({ submit, data }) => {
				pending = true;
				error = '';
				try {
					await submit();
					if (!saveStream.fields.allIssues()?.length) {
						toast.success('Stream saved.');
						if (data.next === '/streams/add?setup=1') {
							label = '';
							source = '';
							preview = '';
						}
					}
				} catch (cause) {
					error = cause instanceof Error ? cause.message : 'Could not save this source.';
				} finally {
					pending = false;
				}
			})}
		>
			<input type="hidden" name="original" value={originalSource} />
			<Field.Group>
				<Field.Field data-invalid={Boolean(saveStream.fields.label.issues()?.length)}>
					<Field.Label for="stream-label">Label</Field.Label>
					<Input
						id="stream-label"
						name="label"
						bind:value={label}
						required
						disabled={pending}
						aria-invalid={Boolean(saveStream.fields.label.issues()?.length)}
						placeholder="e.g. Barn camera"
					/>
				</Field.Field>
				<Field.Field data-invalid={Boolean(saveStream.fields.source.issues()?.length)}>
					<Field.Label for="stream-source">Source</Field.Label>
					<Input
						id="stream-source"
						name="source"
						bind:value={source}
						required
						disabled={pending}
						aria-invalid={Boolean(saveStream.fields.source.issues()?.length)}
						placeholder="rtsp://camera.local/live"
					/>
					<Field.Description
						>Enter the camera's stream address or a local input supported by the detector.</Field.Description
					>
				</Field.Field>
				<Button
					type="button"
					variant="outline"
					disabled={pending || !source.trim()}
					onclick={() => {
						preview = source;
						previewVersion += 1;
					}}>Test preview</Button
				>
			</Field.Group>
			{#if error || saveStream.fields.allIssues()?.length}
				<Alert.Root variant="destructive">
					<Alert.Title>Could not update stream</Alert.Title>
					<Alert.Description
						>{error}
						{#each saveStream.fields.allIssues() ?? [] as issue, index (index)}
							<p>
								{issue.message}
							</p>
						{/each}
					</Alert.Description>
				</Alert.Root>
			{/if}
			<div class="flex flex-wrap gap-2">
				{#if originalSource}
					<Button type="button" variant="destructive" onclick={remove} disabled={pending}
						>Delete</Button
					>
				{/if}
				{#if setupMode && !originalSource}
					<Button
						type="submit"
						name="next"
						value="/streams/add?setup=1"
						variant="outline"
						disabled={pending}>Save and add another</Button
					>
					<Button type="submit" name="next" value="/setup" disabled={pending}
						>{pending ? 'Saving…' : 'Save and return to setup'}</Button
					>
				{:else}
					<Button type="submit" disabled={pending}>{pending ? 'Working…' : 'Save'}</Button>
				{/if}
			</div>
		</form>
		{#if preview}
			<div class="w-full max-w-lg min-w-0">
				{#key previewVersion}
					<Stream {label} source={preview} showLoading />
				{/key}
			</div>
		{/if}
	</div>
</section>

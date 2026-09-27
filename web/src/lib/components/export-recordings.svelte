<script lang="ts">
	import { resolve } from '$app/paths';
	import { Download } from '@lucide/svelte';
	import * as v from 'valibot';
	import { SvelteURLSearchParams } from 'svelte/reactivity';
	import { Button, buttonVariants } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import * as Dialog from '$lib/components/ui/dialog';
	import * as Field from '$lib/components/ui/field';
	import { recordingExportInput } from '$lib/detections';
	import { getExportCount } from '$lib/remote/detections.remote';
	import type { Stage } from '$lib/schema';

	let { type, stage }: { type?: string; stage?: Stage } = $props();
	let open = $state(false);
	let from = $state('');
	let to = $state('');
	const selection = $derived(
		v.safeParse(recordingExportInput, { type, stage, from: from || undefined, to: to || undefined })
	);
	const count = $derived(open && selection.success ? getExportCount(selection.output) : null);
	const search = $derived.by(() => {
		const params = new SvelteURLSearchParams();
		for (const [key, value] of Object.entries({ type, stage, from, to })) {
			if (value) params.set(key, value);
		}
		return params.toString();
	});
</script>

<Dialog.Root bind:open>
	<Dialog.Trigger class={buttonVariants({ variant: 'outline' })}>
		<Download data-icon="inline-start" aria-hidden="true" />Export recordings
	</Dialog.Trigger>
	<Dialog.Content>
		<Dialog.Header>
			<Dialog.Title>Export recordings</Dialog.Title>
			<Dialog.Description>
				Download images, videos and detection details in one ZIP to share for model improvement.
			</Dialog.Description>
		</Dialog.Header>
		<p class="text-sm">{type ?? 'All categories'} · {stage ?? 'All stages'}</p>
		<Field.Group>
			<Field.Group class="sm:flex-row">
				<Field.Field data-invalid={!selection.success || undefined}>
					<Field.Label for="export-from">From date</Field.Label>
					<Input
						id="export-from"
						type="date"
						bind:value={from}
						max={to || undefined}
						aria-invalid={!selection.success}
						aria-describedby={selection.success ? 'export-dates-help' : 'export-dates-error'}
					/>
				</Field.Field>
				<Field.Field data-invalid={!selection.success || undefined}>
					<Field.Label for="export-to">To date</Field.Label>
					<Input
						id="export-to"
						type="date"
						bind:value={to}
						min={from || undefined}
						aria-invalid={!selection.success}
						aria-describedby={selection.success ? 'export-dates-help' : 'export-dates-error'}
					/>
				</Field.Field>
			</Field.Group>
			<Field.Description id="export-dates-help"
				>Optional. Leave both empty to include all dates.</Field.Description
			>
		</Field.Group>
		{#if !selection.success}
			<p id="export-dates-error" role="alert" class="text-sm text-destructive">
				{selection.issues[0].message}
			</p>
		{:else if count}
			{#await count}
				<p role="status" class="text-sm text-muted-foreground">Counting recordings…</p>
			{:then total}
				<p role="status" class="text-sm text-muted-foreground">
					{total === 0
						? 'No recordings match these filters.'
						: `${total} ${total === 1 ? 'recording' : 'recordings'} selected, including all pages.`}
				</p>
				<Dialog.Footer>
					<Button
						href={resolve(`/detections/export?${search}`)}
						download
						data-sveltekit-reload
						disabled={!total}
					>
						<Download data-icon="inline-start" aria-hidden="true" />Download ZIP
					</Button>
				</Dialog.Footer>
			{:catch}
				<p role="alert" class="text-sm text-destructive">
					Could not read the recordings. Close this window and try again.
				</p>
			{/await}
		{/if}
	</Dialog.Content>
</Dialog.Root>

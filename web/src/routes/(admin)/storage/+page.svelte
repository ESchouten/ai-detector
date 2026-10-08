<script lang="ts">
	import { enhance } from '$app/forms';
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Progress } from '$lib/components/ui/progress';
	import * as Field from '$lib/components/ui/field';
	import * as Alert from '$lib/components/ui/alert';
	import PageHeader from '$lib/components/page-header.svelte';
	import { calendarDate, gigabytes, plural } from '$lib/format';
	let { data, form } = $props();
	const used = $derived(data.space.total - data.space.available);
</script>

<svelte:head><title>Storage · AI Detector</title></svelte:head>
<section class="page-narrow">
	<PageHeader
		back={{ href: resolve('/settings'), label: 'Settings' }}
		title="Storage"
		description="Recordings are kept until you remove them. Nothing is deleted automatically."
	/>

	<div class="panel flex flex-col gap-3 p-5">
		<div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
			<p class="text-lg font-semibold tabular-nums">{gigabytes(data.space.available)} free</p>
			<p class="text-sm text-muted-foreground tabular-nums">
				{gigabytes(used)} used of {gigabytes(data.space.total)}
			</p>
		</div>
		<Progress
			value={data.space.total ? (100 * used) / data.space.total : 0}
			aria-label="Storage used"
			class={data.space.low ? '[&>div]:bg-status-bad' : ''}
		/>
	</div>
	{#if data.space.low}
		<Alert.Root variant="destructive">
			<Alert.Title>Storage is almost full</Alert.Title>
			<Alert.Description>Free some space so new recordings can be saved.</Alert.Description>
		</Alert.Root>
	{/if}
	{#if form?.message}<p role="status" class="text-sm font-medium">{form.message}</p>{/if}

	<section class="flex flex-col gap-4" aria-labelledby="storage-cleanup">
		<div class="flex flex-col gap-1">
			<h2 id="storage-cleanup" class="text-base font-semibold">Remove old recordings</h2>
			<p class="text-sm text-muted-foreground">
				Choose a date to see how many recordings would be removed. Export the ones you want to keep
				first from
				<a
					href={resolve('/detections')}
					class="font-medium text-foreground underline underline-offset-4">Recordings</a
				>.
			</p>
		</div>
		<form method="POST" action="?/preview" use:enhance class="flex flex-wrap items-end gap-3">
			<Field.Field class="w-auto">
				<Field.Label for="before-date">Recordings before</Field.Label>
				<Input
					id="before-date"
					name="before"
					type="date"
					max={new Date().toISOString().slice(0, 10)}
					required
				/>
			</Field.Field>
			<Button type="submit" variant="outline">Review</Button>
		</form>
		{#if form?.revision}
			<div class="panel flex flex-col items-start gap-3 p-4">
				<p class="text-sm font-medium">
					{plural(form.count ?? 0, [
						`# recording before ${calendarDate(form.before)}`,
						`# recordings before ${calendarDate(form.before)}`
					])}
				</p>
				<p class="text-sm text-muted-foreground">
					{form.count
						? 'Removing them cannot be undone. Settings and newer recordings are kept.'
						: 'There is nothing to remove before this date.'}
				</p>
				{#if form.count}
					<form method="POST" action="?/remove" use:enhance>
						<input type="hidden" name="before" value={form.before} />
						<input type="hidden" name="revision" value={form.revision} />
						<Button type="submit" variant="destructive">
							{plural(form.count, ['Remove # recording', 'Remove # recordings'])}
						</Button>
					</form>
				{/if}
			</div>
		{/if}
	</section>

	<section class="flex flex-col gap-4 border-t pt-6" aria-labelledby="storage-cache">
		<div class="flex flex-col gap-1">
			<h2 id="storage-cache" class="text-base font-semibold">Model cache</h2>
			<p class="text-sm text-muted-foreground">
				Prepared models and unused downloads. Pause monitoring before clearing them; the next start
				prepares models again, which can take several minutes on NVIDIA hardware.
			</p>
		</div>
		<form method="POST" action="?/cache" use:enhance>
			<Button type="submit" variant="outline" disabled={!data.managed}>Clear model cache</Button>
		</form>
	</section>
</section>

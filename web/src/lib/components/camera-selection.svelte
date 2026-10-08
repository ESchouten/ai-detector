<script lang="ts">
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Button } from '$lib/components/ui/button';
	import * as Field from '$lib/components/ui/field';
	import CameraPicture from './camera-picture.svelte';
	import { plural } from '$lib/format';
	let {
		cameras,
		selected = $bindable(),
		disabled = false
	}: {
		cameras: { id: string; source: string; label: string }[];
		selected: string[];
		disabled?: boolean;
	} = $props();
	const all = $derived(cameras.every((camera) => selected.includes(camera.source)));
</script>

<Field.Set>
	<div class="flex flex-wrap items-end justify-between gap-3">
		<div class="flex flex-col gap-1.5">
			<Field.Legend class="mb-0">Which cameras should it watch?</Field.Legend>
			<Field.Description>A camera can be watched by several detectors.</Field.Description>
		</div>
		{#if cameras.length > 1}
			<Button
				variant="outline"
				size="sm"
				{disabled}
				onclick={() => (selected = all ? [] : cameras.map((camera) => camera.source))}
				>{all ? 'Clear selection' : 'Select all cameras'}</Button
			>
		{/if}
	</div>
	<div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
		{#each cameras as camera (camera.id)}
			{@const checked = selected.includes(camera.source)}
			<div
				class={[
					'relative rounded-xl outline-2 outline-offset-2 transition-[outline-color]',
					checked ? 'outline-primary' : 'outline-transparent'
				]}
			>
				<CameraPicture id={camera.id} label={camera.label}>
					{#snippet caption()}
						<p class="min-w-0 truncate pl-8 text-sm font-medium">{camera.label}</p>
					{/snippet}
				</CameraPicture>
				<label
					for={`detector-camera-${camera.id}`}
					class="absolute inset-0 z-10 flex cursor-pointer items-end rounded-xl p-3 has-disabled:cursor-default"
				>
					<Checkbox
						id={`detector-camera-${camera.id}`}
						{checked}
						class="size-5 border-white/70 bg-black/40"
						onCheckedChange={(value) => {
							selected = value
								? [...selected, camera.source]
								: selected.filter((source) => source !== camera.source);
						}}
						{disabled}
					/>
					<span class="sr-only">{camera.label}</span>
				</label>
			</div>
		{/each}
	</div>
	<p role="status" class="text-sm text-muted-foreground">
		{selected.length
			? plural(selected.length, ['# camera selected', '# cameras selected'])
			: 'Choose at least one camera to continue.'}
	</p>
</Field.Set>

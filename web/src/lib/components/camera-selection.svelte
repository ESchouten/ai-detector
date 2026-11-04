<script lang="ts">
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Button } from '$lib/components/ui/button';
	import * as Field from '$lib/components/ui/field';
	import * as Dialog from '$lib/components/ui/dialog';
	import { SquareDashed } from '@lucide/svelte';
	import CameraPicture from './camera-picture.svelte';
	import AreaOutline from './area-outline.svelte';
	import DetectionArea from './detection-area.svelte';
	import { plural } from '$lib/format';
	import { withArea, type Area, type Areas } from '$lib/detector-editor';
	type Choice = { id: string; source: string; label: string };
	let {
		cameras,
		selected = $bindable(),
		areas = $bindable(),
		disabled = false
	}: {
		cameras: Choice[];
		selected: string[];
		/** The area each selected camera is watched in, by its source. */
		areas: Areas | undefined;
		disabled?: boolean;
	} = $props();
	const all = $derived(cameras.every((camera) => selected.includes(camera.source)));
	let editing = $state<Choice>();
	const areaOf = (camera: Choice): Area => (areas?.[camera.source] as Area | undefined) ?? [];
	function select(chosen: string[]) {
		selected = chosen;
		for (const source of Object.keys(areas ?? {}))
			if (!chosen.includes(source)) areas = withArea(areas, source, []);
	}
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
				onclick={() => select(all ? [] : cameras.map((camera) => camera.source))}
				>{all ? 'Clear selection' : 'Select all cameras'}</Button
			>
		{/if}
	</div>
	<div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
		{#each cameras as camera (camera.id)}
			{@const checked = selected.includes(camera.source)}
			{@const area = areaOf(camera)}
			<div
				class={[
					'relative rounded-xl outline-2 outline-offset-2 transition-[outline-color]',
					checked ? 'outline-primary' : 'outline-transparent'
				]}
			>
				<CameraPicture id={camera.id} label={camera.label}>
					{#snippet overlay(size)}
						{#if checked && area.length}<AreaOutline {area} {size} />{/if}
					{/snippet}
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
							select(
								value
									? [...selected, camera.source]
									: selected.filter((source) => source !== camera.source)
							);
						}}
						{disabled}
					/>
					<span class="sr-only">{camera.label}</span>
				</label>
				{#if checked}
					<Button
						variant="secondary"
						size="sm"
						class="absolute top-2 right-2 z-20"
						{disabled}
						onclick={() => (editing = camera)}
					>
						<SquareDashed data-icon="inline-start" aria-hidden="true" />
						{area.length ? 'Part of the picture' : 'Whole picture'}
						<span class="sr-only">· {camera.label}</span>
					</Button>
				{/if}
			</div>
		{/each}
	</div>
	<p role="status" class="text-sm text-muted-foreground">
		{selected.length
			? plural(selected.length, ['# camera selected', '# cameras selected'])
			: 'Choose at least one camera to continue.'}
	</p>
</Field.Set>

<Dialog.Root
	open={!!editing}
	onOpenChange={(open) => {
		if (!open) editing = undefined;
	}}
>
	<Dialog.Content class="max-h-[90dvh] overflow-y-auto sm:max-w-3xl">
		{#if editing}
			{@const camera = editing}
			<DetectionArea
				{camera}
				area={areaOf(camera)}
				onDone={(area) => {
					areas = withArea(areas, camera.source, area);
					editing = undefined;
				}}
			/>
		{/if}
	</Dialog.Content>
</Dialog.Root>

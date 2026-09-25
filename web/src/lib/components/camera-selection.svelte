<script lang="ts">
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Badge } from '$lib/components/ui/badge';
	import * as Field from '$lib/components/ui/field';
	import CameraPicture from './camera-picture.svelte';
	let {
		cameras,
		selected = $bindable(),
		disabled = false
	}: {
		cameras: { id: string; source: string; label: string; monitored: boolean }[];
		selected: string[];
		disabled?: boolean;
	} = $props();
</script>

<Field.Set>
	<Field.Legend>Choose cameras</Field.Legend>
	<Field.Description>
		Select one or more cameras for this detector. The same camera can be used by several detectors.
	</Field.Description>
	<Field.Group class="grid gap-4 sm:grid-cols-2">
		{#each cameras as camera (camera.id)}
			<CameraPicture
				id={camera.id}
				label={camera.label}
				class={selected.includes(camera.source) ? 'ring-2 ring-primary' : ''}
			>
				{#snippet overlay()}
					<Field.Field
						orientation="horizontal"
						data-disabled={disabled}
						class="pointer-events-auto gap-2"
					>
						<Checkbox
							id={`detector-camera-${camera.id}`}
							checked={selected.includes(camera.source)}
							onCheckedChange={(checked) => {
								selected = checked
									? [...selected, camera.source]
									: selected.filter((source) => source !== camera.source);
							}}
							{disabled}
						/>
						<Field.Label for={`detector-camera-${camera.id}`} class="min-w-0 flex-1 cursor-pointer">
							<Badge variant="secondary" class="max-w-full text-left whitespace-normal"
								>{camera.label}</Badge
							>
						</Field.Label>
					</Field.Field>
				{/snippet}
			</CameraPicture>
		{/each}
	</Field.Group>
	<p role="status" class="text-sm text-muted-foreground">
		{selected.length ? `${selected.length} selected` : 'Choose at least one camera to continue.'}
	</p>
</Field.Set>

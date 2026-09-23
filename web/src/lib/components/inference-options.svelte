<script lang="ts">
	import { Input } from '$lib/components/ui/input';
	import { Switch } from '$lib/components/ui/switch';
	import * as Field from '$lib/components/ui/field';
	import * as NativeSelect from '$lib/components/ui/native-select';
	import type { DetectorConfig } from '$lib/schema';
	let {
		yolo,
		disabled = false
	}: { yolo: NonNullable<DetectorConfig['yolo']>; disabled?: boolean } = $props();
</script>

<details class="rounded-md border p-4">
	<summary class="cursor-pointer text-sm font-medium">Tracking and overlapping detections</summary>
	<Field.Group class="mt-4">
		<Field.Field>
			<Field.Label for="detector-iou">Overlap threshold (IoU)</Field.Label>
			<Input
				id="detector-iou"
				type="number"
				min="0"
				max="1"
				step="0.01"
				placeholder="Model default"
				bind:value={() => yolo.iou ?? undefined, (value) => (yolo.iou = value)}
				{disabled}
			/>
			<Field.Description
				>Controls removal of overlapping boxes. Lower values remove more boxes; leave blank to use
				the model default.</Field.Description
			>
		</Field.Field>
		<Field.Field orientation="horizontal">
			<Switch
				id="detector-tracking"
				checked={yolo.tracking ?? false}
				onCheckedChange={(value) => (yolo.tracking = value)}
				{disabled}
			/>
			<Field.Label for="detector-tracking">Track objects between frames</Field.Label>
		</Field.Field>
		{#if yolo.tracking}
			<Field.Field>
				<Field.Label for="detector-tracker">Tracker</Field.Label>
				<NativeSelect.Root
					id="detector-tracker"
					value={yolo.tracker ?? ''}
					{disabled}
					onchange={(event) => {
						yolo.tracker = (event.currentTarget.value as typeof yolo.tracker) || undefined;
					}}
				>
					<NativeSelect.Option value="">Ultralytics default</NativeSelect.Option>
					<NativeSelect.Option value="botsort.yaml">BoT-SORT</NativeSelect.Option>
					<NativeSelect.Option value="bytetrack.yaml">ByteTrack</NativeSelect.Option>
				</NativeSelect.Root>
				<Field.Description
					>Live detections can show temporary track IDs. These may change after interruptions and do
					not identify an individual across sessions.</Field.Description
				>
			</Field.Field>
		{/if}
	</Field.Group>
</details>

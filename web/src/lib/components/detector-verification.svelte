<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import * as Field from '$lib/components/ui/field';
	import * as NativeSelect from '$lib/components/ui/native-select';
	import { connectionMatches } from '$lib/llm';
	import type { DetectorConfig, LlmConnection } from '$lib/schema';
	let {
		detector = $bindable(),
		connectionLabel = $bindable(''),
		connections,
		disabled = false,
		addConnection,
		selectConnection
	}: {
		detector: DetectorConfig;
		connectionLabel?: string;
		connections: LlmConnection[];
		disabled?: boolean;
		addConnection: () => void;
		selectConnection: (connection: LlmConnection) => Promise<void>;
	} = $props();
	const steps = $derived(detector.vlm ?? []);
	const settings = $derived(steps[0]);
	const selected = $derived(
		connections.find(
			(connection) =>
				connection.label === connectionLabel && settings && connectionMatches(settings, connection)
		)
	);
	const configured = $derived(steps.some((step) => step.enabled !== false));
	const active = $derived(detector.vlm_enabled !== false && configured);
	function choose(value: string) {
		if (!value) {
			detector.vlm_enabled = false;
			connectionLabel = '';
		} else if (value === 'custom') {
			detector.vlm_enabled = true;
		} else {
			const connection = connections.find(
				({ label }) => label === value.slice('connection:'.length)
			)!;
			void selectConnection(connection);
		}
	}
</script>

<Field.Set>
	<Field.Legend
		>AI verification <span class="font-normal text-muted-foreground">(optional)</span></Field.Legend
	>
	<Field.Description
		>Send event images or video to your chosen AI service before sending alerts. The detector preset
		supplies the question.</Field.Description
	>
	<Field.Group class="gap-4">
		<Field.Field
			><Field.Label for="detector-ai-connection">AI connection</Field.Label><NativeSelect.Root
				id="detector-ai-connection"
				value={!active ? '' : selected ? `connection:${selected.label}` : 'custom'}
				onchange={(event) => choose(event.currentTarget.value)}
				{disabled}
			>
				<NativeSelect.Option value="">Off — use detections directly</NativeSelect.Option>
				{#if configured && !selected}<NativeSelect.Option value="custom"
						>Custom settings from JSON</NativeSelect.Option
					>{/if}
				{#each connections as connection (connection.label)}<NativeSelect.Option
						value={`connection:${connection.label}`}>{connection.label}</NativeSelect.Option
					>{/each}
			</NativeSelect.Root></Field.Field
		>
		<Button type="button" variant="outline" class="self-start" onclick={addConnection} {disabled}
			>Add AI connection</Button
		>
	</Field.Group>
</Field.Set>

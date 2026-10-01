<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import * as Field from '$lib/components/ui/field';
	import * as NativeSelect from '$lib/components/ui/native-select';
	import { clearVerificationKeys, connectionMatches } from '$lib/llm';
	import type { DetectorConfig, LlmConnection } from '$lib/schema';
	let {
		detector = $bindable(),
		connectionLabel = $bindable(''),
		connections,
		disabled = false,
		addConnection,
		selectConnection,
		onChoose
	}: {
		detector: DetectorConfig;
		connectionLabel?: string;
		connections: LlmConnection[];
		disabled?: boolean;
		addConnection: () => void;
		selectConnection: (connection: LlmConnection) => Promise<void>;
		onChoose: () => void;
	} = $props();
	const steps = $derived(detector.vlm ?? []);
	const settings = $derived(steps[0]);
	const selected = $derived(
		connections.find(
			(connection) =>
				connection.label === connectionLabel && settings && connectionMatches(settings, connection)
		)
	);
	const active = $derived(steps.some((step) => step.key != null));
	function choose(value: string) {
		onChoose();
		if (!value) {
			detector = clearVerificationKeys(detector);
			connectionLabel = '';
		} else if (value !== 'custom') {
			const connection = connections.find(
				({ label }) => label === value.slice('connection:'.length)
			)!;
			void selectConnection(connection);
		}
	}
</script>

{#if settings?.prompt.trim()}<Field.Set>
		<Field.Legend
			>Validator <span class="font-normal text-muted-foreground">(optional)</span></Field.Legend
		>
		<Field.Description
			>Check detections with AI before sending alerts. The preset supplies the question.</Field.Description
		>
		<Field.Group class="gap-4">
			{#if connections.length || active}<Field.Field
					><Field.Label for="detector-ai-connection">Connection</Field.Label><NativeSelect.Root
						id="detector-ai-connection"
						value={!active ? '' : selected ? `connection:${selected.label}` : 'custom'}
						onchange={(event) => choose(event.currentTarget.value)}
						{disabled}
					>
						<NativeSelect.Option value="">Off — use detections directly</NativeSelect.Option>
						{#if active && !selected}<NativeSelect.Option value="custom"
								>Custom settings from JSON</NativeSelect.Option
							>{/if}
						{#each connections as connection (connection.label)}<NativeSelect.Option
								disabled={connection.key == null}
								value={`connection:${connection.label}`}>{connection.label}</NativeSelect.Option
							>{/each}
					</NativeSelect.Root></Field.Field
				>{/if}
			<Button type="button" variant="outline" class="self-start" onclick={addConnection} {disabled}
				>{connections.length ? 'Add another connection' : 'Connect validator'}</Button
			>
		</Field.Group>
	</Field.Set>{/if}

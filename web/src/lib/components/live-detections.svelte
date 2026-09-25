<script lang="ts">
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import * as NativeSelect from '$lib/components/ui/native-select';
	import { Badge } from '$lib/components/ui/badge';
	import CardOverlay from './card-overlay.svelte';
	import type { LivePreviewFrame, LivePreviewStatus } from '$lib/live-preview';

	let { id, label }: { id: string; label: string } = $props();
	type RuleView = { label: string; frame: LivePreviewFrame | null; message: string };
	let rules = $state<Record<string, RuleView>>({});
	let selected = $state('');
	let message = $state('Waiting for the detector to analyse a frame…');
	let displayWidth = $state(640);
	const current = $derived(rules[selected]);
	const frame = $derived(current?.frame);

	onMount(() => {
		const connection = new EventSource(resolve(`/cameras/${id}/live`));
		let lastContact = Date.now();
		let interrupted = false;
		function contact() {
			lastContact = Date.now();
			if (interrupted) {
				interrupted = false;
				message = 'Waiting for the detector to analyse a frame…';
			}
		}
		function disconnected() {
			interrupted = true;
			rules = {};
			selected = '';
			message = 'Connection interrupted. Reconnecting to live detections…';
		}
		const watchdog = setInterval(() => {
			if (Date.now() - lastContact > 7000) disconnected();
		}, 1000);
		connection.addEventListener('heartbeat', contact);
		connection.addEventListener('frame', (event: MessageEvent<string>) => {
			contact();
			const frame: LivePreviewFrame = JSON.parse(event.data);
			rules[frame.ruleId] = { label: frame.ruleLabel, frame, message: '' };
			if (!selected) selected = frame.ruleId;
		});
		connection.addEventListener('status', (event: MessageEvent<string>) => {
			contact();
			const status: LivePreviewStatus = JSON.parse(event.data);
			if (status.ruleId) {
				rules[status.ruleId] = {
					label: status.ruleLabel ?? status.ruleId,
					frame: null,
					message: status.message
				};
				if (!selected) selected = status.ruleId;
			} else {
				rules = {};
				selected = '';
				message = status.message;
			}
		});
		connection.onerror = disconnected;
		return () => {
			clearInterval(watchdog);
			connection.close();
		};
	});

	function boxLabel(box: LivePreviewFrame['boxes'][number]): string {
		return [
			box.label,
			box.confidence === null ? null : `${Math.round(box.confidence * 100)}%`,
			box.trackId === null ? null : `#${box.trackId}`
		]
			.filter((part) => part !== null)
			.join(' · ');
	}
</script>

<div class="flex flex-col gap-3">
	<CardOverlay>
		{#if frame}
			<div bind:clientWidth={displayWidth} class="bg-muted">
				<svg
					viewBox={`0 0 ${frame.image.width} ${frame.image.height}`}
					class="block h-auto w-full"
					role="img"
					aria-label={`${label}: ${frame.boxes.length} detected objects. ${frame.boxes.map(boxLabel).join('; ')}`}
				>
					<image
						href={`data:image/jpeg;base64,${frame.image.jpeg}`}
						width={frame.image.width}
						height={frame.image.height}
					/>
					{#each frame.boxes as box, index (index)}
						{@const fontSize = Math.max(14, (frame.image.width / displayWidth) * 12)}
						<rect
							x={box.x1}
							y={box.y1}
							width={box.x2 - box.x1}
							height={box.y2 - box.y1}
							fill="none"
							stroke="#4ade80"
							stroke-width="2"
							vector-effect="non-scaling-stroke"
						/>
						<text
							x={box.x1 + 4}
							y={Math.max(fontSize + 3, box.y1 - 5)}
							font-size={fontSize}
							font-weight="600"
							fill="white"
							stroke="black"
							stroke-width="3"
							paint-order="stroke"
							stroke-linejoin="round">{boxLabel(box)}</text
						>
					{/each}
				</svg>
			</div>
		{:else}
			<div
				role="status"
				class="flex aspect-video items-center justify-center bg-muted px-6 pt-16 pb-6 text-center text-sm text-muted-foreground"
			>
				{current?.message || message}
			</div>
		{/if}
		{#snippet overlay()}
			<div class="flex flex-wrap items-center gap-2 pr-10">
				<Badge variant="secondary" class="max-w-full text-left whitespace-normal">{label}</Badge>
				{#if Object.keys(rules).length > 1}
					<div class="pointer-events-auto max-w-full min-w-0">
						<NativeSelect.Root
							aria-label="Detector"
							bind:value={selected}
							class="h-8 max-w-full bg-background py-1 text-foreground"
						>
							{#each Object.entries(rules) as [ruleId, rule] (ruleId)}
								<NativeSelect.Option value={ruleId}>{rule.label}</NativeSelect.Option>
							{/each}
						</NativeSelect.Root>
					</div>
				{:else if current}
					<Badge variant="secondary" class="max-w-full text-left whitespace-normal"
						>{current.label}</Badge
					>
				{/if}
				{#if frame}
					<Badge variant="secondary"
						>{frame.boxes.length} {frame.boxes.length === 1 ? 'object' : 'objects'}</Badge
					>
					<Badge variant="secondary">{new Date(frame.capturedAt).toLocaleTimeString()}</Badge>
				{/if}
			</div>
		{/snippet}
	</CardOverlay>
	{#if frame?.boxes.some((box) => box.trackId !== null)}
		<p class="px-4 pb-3 text-xs text-muted-foreground">
			# numbers follow objects temporarily. They can change when tracking restarts.
		</p>
	{/if}
</div>

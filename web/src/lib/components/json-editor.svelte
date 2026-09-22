<script lang="ts">
	import { onMount } from 'svelte';
	import type * as Monaco from 'monaco-editor';

	let {
		value = $bindable(''),
		schema,
		height = 420,
		hasErrors = $bindable(false)
	}: {
		value?: string;
		schema?: Record<string, unknown>;
		height?: number | string;
		hasErrors?: boolean;
	} = $props();

	const id = $props.id();
	let container: HTMLDivElement;
	let issues = $state<string[]>([]);
	let editor = $state.raw<Monaco.editor.IStandaloneCodeEditor>();

	$effect(() => {
		if (editor && !editor.hasWidgetFocus() && value !== editor.getValue()) editor.setValue(value);
	});

	onMount(() => {
		let cancelled = false;
		let dispose = () => {};
		async function createEditor() {
			const [{ default: EditorWorker }, { default: JsonWorker }, monaco] = await Promise.all([
				import('monaco-editor/esm/vs/editor/editor.worker?worker'),
				import('monaco-editor/esm/vs/language/json/json.worker?worker'),
				import('monaco-editor')
			]);
			if (cancelled) return;
			self.MonacoEnvironment = {
				getWorker: (_, label) => (label === 'json' ? new JsonWorker() : new EditorWorker())
			};
			const uri = monaco.Uri.parse(`inmemory://model/${encodeURIComponent(id)}.json`);
			monaco.json.jsonDefaults.setDiagnosticsOptions({
				validate: true,
				allowComments: false,
				enableSchemaRequest: false,
				schemas: schema
					? [
							{
								uri: `inmemory://schema/${encodeURIComponent(id)}.json`,
								fileMatch: [uri.toString()],
								schema: JSON.parse(JSON.stringify(schema))
							}
						]
					: []
			});
			const model = monaco.editor.createModel(value, 'json', uri);
			editor = monaco.editor.create(container, {
				model,
				automaticLayout: true,
				formatOnPaste: true,
				formatOnType: true,
				minimap: { enabled: false },
				scrollBeyondLastLine: false,
				tabSize: 2,
				insertSpaces: true,
				wordWrap: 'on'
			});
			function syncMarkers() {
				const markers = monaco.editor.getModelMarkers({ resource: uri });
				hasErrors = markers.some((marker) => marker.severity === monaco.MarkerSeverity.Error);
				issues = markers
					.filter((marker) => marker.severity >= monaco.MarkerSeverity.Warning)
					.map((marker) => `Line ${marker.startLineNumber}: ${marker.message}`);
			}
			const contentSubscription = editor.onDidChangeModelContent(() => {
				value = model.getValue();
				// Syntax errors must disable Save before the asynchronous schema worker replies.
				try {
					JSON.parse(value);
					hasErrors = false;
				} catch {
					hasErrors = true;
				}
			});
			const markerSubscription = monaco.editor.onDidChangeMarkers((resources) => {
				if (resources.some((resource) => resource.toString() === uri.toString())) syncMarkers();
			});
			dispose = () => {
				contentSubscription.dispose();
				markerSubscription.dispose();
				editor?.dispose();
				model.dispose();
			};
		}
		void createEditor().catch(() => {
			if (!cancelled) {
				hasErrors = true;
				issues = ['The editor could not load. Reload this page to try again.'];
			}
		});
		return () => {
			cancelled = true;
			dispose();
		};
	});
</script>

<div class="flex flex-col gap-2">
	<div
		bind:this={container}
		class="overflow-hidden rounded-md border border-input"
		style:height={typeof height === 'number' ? `${height}px` : height}
	></div>
	{#if issues.length > 0}
		<div
			role="alert"
			class="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
		>
			{#each issues as issue, index (index)}<p>{issue}</p>{/each}
		</div>
	{/if}
</div>

<script lang="ts">
	import { onMount } from 'svelte';
	import type * as Monaco from 'monaco-editor';
	import * as Alert from '$lib/components/ui/alert';

	let {
		value = $bindable(''),
		schema,
		height = 420,
		ariaLabel = 'JSON configuration',
		readonly = false
	}: {
		value?: string;
		schema?: Record<string, unknown>;
		height?: number | string;
		ariaLabel?: string;
		readonly?: boolean;
	} = $props();

	const id = $props.id();
	let container: HTMLDivElement;
	let loadError = $state('');
	let editor = $state.raw<Monaco.editor.IStandaloneCodeEditor>();

	$effect(() => {
		editor?.updateOptions({ readOnly: readonly });
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
			let registeredSchema = '';
			function configureSchema() {
				let schemaUri = `inmemory://schema/${encodeURIComponent(id)}.json`;
				try {
					const declared = JSON.parse(value)?.$schema;
					if (typeof declared === 'string') schemaUri = declared;
				} catch {
					// Keep the current schema while an incomplete edit is being typed.
					if (registeredSchema) return;
				}
				if (schemaUri === registeredSchema) return;
				registeredSchema = schemaUri;
				// Monaco gives $schema precedence over fileMatch. Bind that URI to the
				// bundled schema too, so suggestions and diagnostics remain offline.
				monaco.json.jsonDefaults.setDiagnosticsOptions({
					validate: true,
					schemaValidation: 'error',
					allowComments: false,
					enableSchemaRequest: false,
					schemas: schema
						? [
								{
									uri: schemaUri,
									fileMatch: [uri.toString()],
									schema: $state.snapshot(schema)
								}
							]
						: []
				});
			}
			configureSchema();
			const model = monaco.editor.createModel(value, 'json', uri);
			editor = monaco.editor.create(container, {
				model,
				ariaLabel,
				automaticLayout: true,
				formatOnPaste: true,
				formatOnType: true,
				minimap: { enabled: false },
				scrollBeyondLastLine: false,
				tabSize: 2,
				insertSpaces: true,
				wordWrap: 'on'
			});
			const contentSubscription = editor.onDidChangeModelContent(() => {
				value = model.getValue();
				configureSchema();
			});
			dispose = () => {
				contentSubscription.dispose();
				editor?.dispose();
				model.dispose();
			};
		}
		void createEditor().catch(() => {
			if (!cancelled) {
				loadError = 'The editor could not load. Reload this page to try again.';
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
	{#if loadError}
		<Alert.Root variant="destructive"
			><Alert.Title>Editor unavailable</Alert.Title><Alert.Description
				>{loadError}</Alert.Description
			></Alert.Root
		>
	{/if}
</div>

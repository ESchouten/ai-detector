<script lang="ts">
	import { onMount } from 'svelte';
	import { FolderOpen, LoaderCircle } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Progress } from '$lib/components/ui/progress';
	import * as Field from '$lib/components/ui/field';
	import {
		getImportStatus,
		pickImportFolder,
		inspectInstallation,
		importInstallation,
		cancelInstallationImport
	} from '$lib/remote/installation-import.remote';
	import type { ImportStatus } from '$lib/installation-import';
	import { plural } from '$lib/format';
	import { errorMessage } from '$lib/remote-errors';

	let {
		oncomplete,
		opened = $bindable(false)
	}: { oncomplete: () => Promise<void>; opened?: boolean } = $props();
	let manual = $state(false);
	let folder = $state('');
	let busy = $state(false);
	let message = $state('');
	let closed = $state(false);
	let keepRecordings = $state(false);
	let local = $state(true);
	let status = $state<ImportStatus>({ phase: 'idle', copiedBytes: 0, totalBytes: 0 });
	const copying = $derived(status.phase === 'copying');
	const summary = $derived(status.summary);
	const locked = $derived(status.keepRecordings !== undefined);

	function size(bytes: number): string {
		return bytes < 1e9 ? `${(bytes / 1e6).toFixed(1)} MB` : `${(bytes / 1e9).toFixed(1)} GB`;
	}

	async function refresh(): Promise<void> {
		await getImportStatus().refresh();
		const response = await getImportStatus();
		local = response.local;
		if (!response.status) return;
		status = response.status;
		if (status.keepRecordings !== undefined) keepRecordings = status.keepRecordings;
		if (status.phase !== 'idle') opened = true;
		if (status.phase === 'complete') await oncomplete();
	}

	onMount(() => {
		void refresh().catch(() => {
			message = 'Could not read the import progress. Reopen setup to try again.';
		});
	});

	async function run(operation: () => Promise<void>): Promise<void> {
		busy = true;
		message = '';
		try {
			await operation();
		} catch (error) {
			message = errorMessage(error, 'Import could not finish. Try again.');
		} finally {
			busy = false;
		}
	}

	async function inspect(): Promise<void> {
		await inspectInstallation(folder);
		closed = false;
		await refresh();
	}

	async function choose(): Promise<void> {
		await run(async () => {
			const selected = await pickImportFolder();
			if (selected) {
				folder = selected;
				await inspect();
			}
		});
	}

	async function start(): Promise<void> {
		if (!summary || !closed) return;
		await run(async () => {
			await importInstallation({ id: summary.id, keepRecordings, previousAppClosed: true });
			await refresh();
		});
	}

	$effect(() => {
		if (!copying) return;
		let stopped = false;
		let timer: ReturnType<typeof setTimeout>;
		async function poll() {
			try {
				await refresh();
				message = '';
			} catch {
				message = 'Reconnecting to the import…';
			}
			if (!stopped) timer = setTimeout(poll, 1000);
		}
		timer = setTimeout(poll, 1000);
		return () => {
			stopped = true;
			clearTimeout(timer);
		};
	});
</script>

{#if !opened}
	<div class="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
		<div class="flex min-w-0 flex-col">
			<p class="text-sm font-medium">Moving from an earlier AI Detector?</p>
			<p class="text-sm text-muted-foreground">
				Bring its cameras, detectors, alerts and recordings along.
			</p>
		</div>
		<Button
			variant="outline"
			onclick={() => {
				opened = true;
			}}>Use existing setup</Button
		>
	</div>
{:else}
	<section aria-label="Import previous installation" class="flex w-full flex-col gap-5 text-left">
		<div class="flex flex-col gap-2">
			<h1 class="text-2xl font-semibold tracking-tight sm:text-3xl">Use your existing setup</h1>
			<p class="leading-relaxed text-muted-foreground">
				Bring your cameras, detectors, alerts and recordings from your previous AI Detector folder.
			</p>
		</div>
		{#if !local}
			<p class="text-sm">
				Open the localhost dashboard on the computer running AI Detector to choose its old folder.
			</p>
		{:else if !summary}
			<p class="text-sm text-muted-foreground">
				Choose the folder containing your old config.json, usually next to the old application.
			</p>
			<div class="flex flex-wrap gap-2">
				<Button onclick={choose} disabled={busy}
					><FolderOpen data-icon="inline-start" />Choose old folder</Button
				>
				<Button
					variant="outline"
					onclick={() => {
						manual = !manual;
					}}
					disabled={busy}>Enter folder path</Button
				>
			</div>
		{:else}
			<div class="space-y-2 text-sm">
				<p class="font-medium">
					{plural(summary.cameras, ['# camera', '# cameras'])} · {plural(summary.detectors, [
						'# detector',
						'# detectors'
					])} · {plural(summary.recordings, ['# recording', '# recordings'])}
				</p>
				<p class="break-all text-muted-foreground">From: {summary.source}</p>
				<p class="break-all text-muted-foreground">To: {summary.destination}</p>
				{#each summary.notes as note (note)}<p class="text-muted-foreground">{note}</p>{/each}
			</div>
			{#if copying}
				<div class="space-y-3" role="status">
					<p class="text-sm">
						{status.message ?? 'Copying your files…'}
						{size(status.copiedBytes)} / {size(status.totalBytes)}
					</p>
					<Progress
						value={status.totalBytes ? (100 * status.copiedBytes) / status.totalBytes : 0}
						aria-label="Import progress"
					/>
					<p class="text-sm text-muted-foreground">
						Keep AI Detector open. You can close this browser tab.
					</p>
				</div>
			{:else}
				<p class="text-sm text-muted-foreground">
					Your original files will stay in place. Monitoring starts when you’re ready in the final
					setup step.
				</p>
				{#if summary.recordingBytes > 0}
					<details class="text-sm">
						<summary class="cursor-pointer font-medium">Recording storage</summary>
						<div class="mt-3 flex flex-col gap-2">
							<label class="flex items-center gap-2"
								><Checkbox bind:checked={keepRecordings} disabled={locked || busy} />Keep recordings
								in their current folder</label
							>
							<p class="text-muted-foreground">
								Saves {size(summary.recordingBytes)} of copying. Keep the old folder and drive connected;
								new recordings will also be saved there.
							</p>
						</div>
					</details>
				{/if}
				<label class="flex items-center gap-2 text-sm"
					><Checkbox bind:checked={closed} disabled={busy} />I’ve closed the previous AI Detector</label
				>
				<div class="flex flex-wrap gap-2">
					<Button onclick={start} disabled={busy || !closed}
						>{#if busy}<LoaderCircle class="animate-spin" data-icon="inline-start" />{/if}{locked
							? 'Resume import'
							: 'Import and review setup'}</Button
					>
					{#if status.canRestart !== false}<Button
							variant="outline"
							onclick={() => {
								status = { phase: 'idle', copiedBytes: 0, totalBytes: 0 };
								message = '';
							}}
							disabled={busy}>Choose another folder</Button
						>{/if}
				</div>
			{/if}
		{/if}
		{#if manual && !summary && local}
			<form
				onsubmit={(event) => {
					event.preventDefault();
					void run(inspect);
				}}
				class="flex flex-col gap-3"
			>
				<Field.Field
					><Field.Label for="import-folder">Old application folder</Field.Label><Input
						id="import-folder"
						bind:value={folder}
						disabled={busy}
						required
					/></Field.Field
				>
				<Button type="submit" class="self-start" disabled={busy || !folder.trim()}
					>Find existing setup</Button
				>
			</form>
		{/if}
		{#if message || (status.message && !copying)}<p
				role={message || status.phase === 'failed' ? 'alert' : 'status'}
				class="text-sm"
				class:text-danger-foreground={Boolean(message) || status.phase === 'failed'}
			>
				{message || status.message}
			</p>{/if}
		{#if !copying && status.canRestart !== false}<Button
				variant="outline"
				class="self-start"
				onclick={() =>
					run(async () => {
						if (local) {
							await cancelInstallationImport();
							await refresh();
						}
						opened = false;
					})}
				disabled={busy}>{summary ? 'Cancel import' : 'Back'}</Button
			>{/if}
	</section>
{/if}

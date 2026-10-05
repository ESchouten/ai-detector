<script lang="ts">
	import { untrack } from 'svelte';
	import { HeartPulse } from '@lucide/svelte';
	import { toast } from 'svelte-sonner';
	import * as v from 'valibot';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import * as Alert from '$lib/components/ui/alert';
	import * as Field from '$lib/components/ui/field';
	import SecretInput from './secret-input.svelte';
	import { heartbeatInput } from '$lib/configuration';
	import { errorMessage } from '$lib/remote-errors';
	import { getHeartbeat, saveHeartbeat } from '$lib/remote/settings.remote';

	// An outside service notices when this computer stops: the detector calls it while it runs.
	let { managed }: { managed: boolean } = $props();
	const saved = $derived(await getHeartbeat());
	let editing = $state(false);
	let url = $state(untrack(() => saved?.url ?? ''));
	let interval = $state(untrack(() => saved?.interval ?? 60));
	let pending = $state(false);
	let error = $state('');
	const host = $derived.by(() => {
		try {
			return saved ? new URL(saved.url).host : '';
		} catch {
			return '';
		}
	});

	function edit() {
		url = saved?.url ?? '';
		interval = saved?.interval ?? 60;
		error = '';
		editing = true;
	}
	async function save(next: { url: string; interval: number } | null) {
		// Check here as well: the server only answers a rejected request with "Bad Request".
		const checked = v.safeParse(heartbeatInput, next);
		if (!checked.success) {
			error = checked.issues[0].message;
			return;
		}
		pending = true;
		error = '';
		try {
			await saveHeartbeat(checked.output).updates(getHeartbeat());
			toast.success(next ? 'Heartbeat saved.' : 'Heartbeat turned off.');
			editing = false;
		} catch (cause) {
			error = errorMessage(cause, 'The heartbeat could not be saved. Your changes are still here.');
		} finally {
			pending = false;
		}
	}
</script>

<section class="flex flex-col gap-3" aria-labelledby="heartbeat-title">
	<div class="flex flex-col gap-1">
		<h2 id="heartbeat-title" class="text-base font-semibold">Heartbeat</h2>
		<p class="text-sm leading-relaxed text-muted-foreground">
			Get warned when this computer or AI Detector stops. While monitoring runs, the detector calls
			an address you choose; a service such as Healthchecks.io or Uptime Kuma alerts you when the
			calls stop coming.
		</p>
	</div>
	<div class="panel flex flex-col gap-4 p-4">
		{#if editing}
			<form
				class="flex flex-col gap-4"
				onsubmit={(event) => {
					event.preventDefault();
					void save({ url, interval });
				}}
			>
				<Field.Field>
					<Field.Label for="heartbeat-url">Address to call</Field.Label>
					<SecretInput
						id="heartbeat-url"
						name="address"
						bind:value={url}
						disabled={pending}
						required
						placeholder="https://hc-ping.com/your-check-id"
						aria-describedby="heartbeat-url-help"
					/>
					<Field.Description id="heartbeat-url-help">
						The ping or push address your monitoring service gives you.
					</Field.Description>
				</Field.Field>
				<Field.Field class="max-w-48">
					<Field.Label for="heartbeat-interval">Call every (seconds)</Field.Label>
					<Input
						id="heartbeat-interval"
						type="number"
						min="5"
						max="86400"
						step="1"
						bind:value={interval}
						disabled={pending}
						required
					/>
				</Field.Field>
				{#if error}
					<Alert.Root variant="destructive">
						<Alert.Title>Heartbeat needs attention</Alert.Title>
						<Alert.Description>{error}</Alert.Description>
					</Alert.Root>
				{/if}
				<p class="text-sm text-muted-foreground">
					{managed
						? 'Saving restarts monitoring for a moment so the detector picks up the change.'
						: 'Restart your detector after saving so it picks up the change.'}
				</p>
				<div class="flex flex-wrap gap-3">
					<Button type="submit" disabled={pending || !url.trim()}>
						{pending ? 'Saving…' : 'Save heartbeat'}
					</Button>
					<Button variant="outline" disabled={pending} onclick={() => (editing = false)}>
						Cancel
					</Button>
				</div>
			</form>
		{:else}
			<div class="flex flex-wrap items-center gap-x-4 gap-y-3">
				<span
					class="flex size-9 shrink-0 items-center justify-center rounded-lg bg-secondary text-secondary-foreground"
				>
					<HeartPulse class="size-[1.125rem]" aria-hidden="true" />
				</span>
				<div class="flex min-w-0 flex-1 basis-48 flex-col">
					{#if saved}
						<p class="text-sm font-medium break-words">
							{host ? `Calling ${host}` : 'Calling the saved address'}
						</p>
						<p class="text-sm text-muted-foreground">
							Every {saved.interval} seconds while monitoring runs
						</p>
					{:else}
						<p class="text-sm font-medium">Off</p>
						<p class="text-sm text-muted-foreground">Nothing is called.</p>
					{/if}
				</div>
				<div class="flex flex-wrap gap-2">
					<Button variant="outline" size="sm" disabled={pending} onclick={edit}>
						{saved ? 'Change' : 'Set up'}
					</Button>
					{#if saved}
						<Button variant="ghost" size="sm" disabled={pending} onclick={() => save(null)}>
							Turn off
						</Button>
					{/if}
				</div>
			</div>
			{#if error}
				<p role="alert" class="text-sm text-danger-foreground">{error}</p>
			{/if}
		{/if}
	</div>
</section>

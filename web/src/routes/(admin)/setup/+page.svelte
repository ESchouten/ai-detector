<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import * as Card from '$lib/components/ui/card';
	import * as Field from '$lib/components/ui/field';
	import * as NativeSelect from '$lib/components/ui/native-select';
	import * as Alert from '$lib/components/ui/alert';
	import DetectorRuntime from '$lib/components/detector-runtime.svelte';
	import { getConfig } from '$lib/remote/config.remote';
	import { finishSetup } from '$lib/remote/setup.remote';
	import Stream from '../streams/stream.svelte';

	const saved = await getConfig();
	let configured = $state(saved.config.detectors.length > 0);
	let label = $state('Barn camera');
	let source = $state('');
	let preset = $state<'calving' | 'mounts' | 'general'>('calving');
	let preview = $state('');
	let saving = $state(false);
	let error = $state('');

	async function save(event: SubmitEvent) {
		event.preventDefault();
		saving = true;
		error = '';
		try {
			await finishSetup({ label, source, preset });
			configured = true;
			preview = '';
		} catch (cause) {
			error =
				cause instanceof Error
					? cause.message
					: 'Could not save setup. Please check the camera address and try again.';
		} finally {
			saving = false;
		}
	}
</script>

<svelte:head><title>Setup · AI Detector</title></svelte:head>

<section class="flex w-full max-w-3xl flex-col gap-6 pb-8">
	<header class="flex flex-col gap-2">
		<h1 class="text-2xl font-semibold tracking-tight">
			{configured ? 'Your detector' : 'Set up your first camera'}
		</h1>
		<p class="text-muted-foreground">
			{configured
				? 'Start detection here. You can add cameras and alerts whenever you need them.'
				: 'Connect a camera, choose what to watch for, and start detection on this computer.'}
		</p>
	</header>

	{#if !configured}
		<Card.Root>
			<Card.Header>
				<Card.Title>1. Connect your camera</Card.Title>
				<Card.Description>Keep this computer and your camera on the same network.</Card.Description>
			</Card.Header>
			<Card.Content>
				<form class="flex flex-col gap-6" onsubmit={save}>
					<Field.Group>
						<Field.Field>
							<Field.Label for="camera-name">Camera name</Field.Label>
							<Input
								id="camera-name"
								bind:value={label}
								required
								autocomplete="off"
								placeholder="e.g. Calving pen"
							/>
						</Field.Field>
						<Field.Field>
							<Field.Label for="camera-address">Camera stream address</Field.Label>
							<Input
								id="camera-address"
								bind:value={source}
								required
								autocomplete="off"
								spellcheck={false}
								placeholder="rtsp://username:password@192.168.1.50/stream"
								aria-describedby="camera-help"
							/>
							<Field.Description id="camera-help"
								>Find the RTSP address in your camera’s settings or ask your camera installer. It is
								different from the camera’s web page.</Field.Description
							>
						</Field.Field>
						{#if source.trim().match(/^rtsps?:\/\//i)}<Button
								variant="outline"
								onclick={() => {
									preview = source.trim();
								}}>Check camera picture</Button
							>{/if}
						{#if preview}<div class="max-w-lg">
								<Stream {label} source={preview} disableLink hideOverlay />
							</div>{/if}
						<Field.Field>
							<Field.Label for="detection-preset">2. What should we watch for?</Field.Label>
							<NativeSelect.Root id="detection-preset" bind:value={preset}>
								<NativeSelect.Option value="calving">Calving signs</NativeSelect.Option>
								<NativeSelect.Option value="mounts">Cow mounting behaviour</NativeSelect.Option>
								<NativeSelect.Option value="general"
									>General objects (people, animals, vehicles)</NativeSelect.Option
								>
							</NativeSelect.Root>
							<Field.Description
								>Detections are saved on this computer. The model downloads automatically at first
								start. You can adjust detection settings later.</Field.Description
							>
						</Field.Field>
					</Field.Group>
					{#if error}<Alert.Root variant="destructive"
							><Alert.Title>Setup could not be saved</Alert.Title><Alert.Description
								>{error}</Alert.Description
							></Alert.Root
						>{/if}
					<Button type="submit" disabled={saving}
						>{saving ? 'Checking and saving…' : 'Save camera and continue'}</Button
					>
				</form>
			</Card.Content>
		</Card.Root>
	{:else}
		<Alert.Root
			><Alert.Title>Camera settings saved</Alert.Title><Alert.Description
				>Your recordings stay on this computer. Keep the application open and prevent this computer
				from sleeping while detection is needed.</Alert.Description
			></Alert.Root
		>
	{/if}

	<DetectorRuntime {configured} />
	{#if configured}
		<div class="flex flex-wrap gap-3">
			<Button href="/notifications/add" variant="outline">Add Telegram alerts</Button>
			<Button href="/detectors" variant="outline">Edit detectors</Button>
			<Button href="/streams/add" variant="outline">Add another camera</Button>
		</div>
	{/if}
	<p class="text-sm text-muted-foreground">
		Detection resumes next time you open the application, unless you choose Stop detection. Closing
		this browser tab leaves detection running. Keep the application open while detection is needed.
	</p>
</section>

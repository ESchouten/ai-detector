<script lang="ts">
	import { untrack } from 'svelte';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { Button } from '$lib/components/ui/button';
	import * as NativeSelect from '$lib/components/ui/native-select';
	import * as Field from '$lib/components/ui/field';
	import CameraPicture from '$lib/components/camera-picture.svelte';
	import PlusIcon from '@lucide/svelte/icons/plus';
	import VideoIcon from '@lucide/svelte/icons/video';
	import BellIcon from '@lucide/svelte/icons/bell';
	import SlidersHorizontalIcon from '@lucide/svelte/icons/sliders-horizontal';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import CameraEditor from '$lib/components/camera-editor.svelte';
	import CameraSetupProgress from '$lib/components/camera-setup-progress.svelte';
	import DetectorRuntime from '$lib/components/detector-runtime.svelte';
	import { getCameras } from '$lib/remote/stream.remote';
	const cameras = $derived(await getCameras());
	const addingFirstCamera = untrack(() => cameras.length === 0);
	const incomplete = $derived(cameras.filter((camera) => !camera.setupComplete));
	const selected = $derived(
		cameras.find((camera) => camera.id === page.url.searchParams.get('camera')) ??
			incomplete[0] ??
			cameras[0]
	);
</script>

<svelte:head><title>{cameras.length ? 'Settings' : 'Setup'} · AI Detector</title></svelte:head>
{#if addingFirstCamera || cameras.length === 0}<CameraEditor />{:else}
	<section class="settings-page">
		<header class="flex flex-wrap items-start justify-between gap-4">
			<div class="space-y-2">
				<h1 class="settings-heading">Settings</h1>
				<p class="settings-description">Keep your cameras, recordings, and alerts ready.</p>
			</div>
			<Button href={resolve('/streams/add')} variant="outline"><PlusIcon />Add a camera</Button>
		</header>
		<div class="settings-layout">
			<div class="flex min-w-0 flex-col gap-6">
				<DetectorRuntime configured={cameras.some((camera) => camera.monitored)} />
				<section aria-labelledby="camera-setup-heading" class="flex min-w-0 flex-col gap-4">
					<div class="flex flex-wrap items-end justify-between gap-3">
						<h2 id="camera-setup-heading" class="text-lg font-semibold">Camera setup</h2>
						{#if cameras.length > 1}
							<Field.Field class="w-full sm:w-auto sm:min-w-56">
								<Field.Label for="setup-camera">Select a camera</Field.Label>
								<NativeSelect.Root
									id="setup-camera"
									value={selected.id}
									onchange={(event) => goto(resolve(`/setup?camera=${event.currentTarget.value}`))}
								>
									{#each cameras as camera (camera.id)}
										<NativeSelect.Option value={camera.id}
											>{camera.label}{camera.setupComplete
												? ''
												: ' · Continue setup'}</NativeSelect.Option
										>
									{/each}
								</NativeSelect.Root>
							</Field.Field>
						{/if}
					</div>
					{#key selected.id}<CameraSetupProgress id={selected.id} />{/key}
				</section>
			</div>
			<aside class="settings-aside" aria-label="Camera preview and settings">
				<section class="space-y-3">
					<h2 class="text-base font-semibold">{selected.label}</h2>
					<p class="settings-description">
						{selected.monitored
							? 'Check the live picture or see what the detector recognises.'
							: 'Check the live picture from this camera.'}
					</p>
					{#key selected.id}<CameraPicture
							id={selected.id}
							label={selected.label}
							monitored={selected.monitored}
						/>{/key}
				</section>
				<nav aria-label="Manage settings" class="divide-y border-t">
					<a
						href={resolve('/streams')}
						class="flex items-start gap-3 rounded-sm py-5 focus-visible:outline-2 focus-visible:outline-ring"
					>
						<VideoIcon class="mt-0.5 size-5 shrink-0" />
						<div class="min-w-0 flex-1">
							<h2 class="text-sm font-medium">Manage cameras</h2>
							<p class="settings-description mt-1">Names, connections, and pictures.</p>
						</div>
						<ChevronRightIcon class="mt-0.5 size-4 shrink-0 text-muted-foreground" />
					</a>
					<a
						href={resolve('/notifications')}
						class="flex items-start gap-3 rounded-sm py-5 focus-visible:outline-2 focus-visible:outline-ring"
					>
						<BellIcon class="mt-0.5 size-5 shrink-0" />
						<div class="min-w-0 flex-1">
							<h2 class="text-sm font-medium">Phone alerts</h2>
							<p class="settings-description mt-1">Choose who receives Telegram messages.</p>
						</div>
						<ChevronRightIcon class="mt-0.5 size-4 shrink-0 text-muted-foreground" />
					</a>
					<a
						href={resolve('/detectors')}
						class="flex items-start gap-3 rounded-sm py-5 focus-visible:outline-2 focus-visible:outline-ring"
					>
						<SlidersHorizontalIcon class="mt-0.5 size-5 shrink-0" />
						<div class="min-w-0 flex-1">
							<h2 class="text-sm font-medium">Monitoring rules</h2>
							<p class="settings-description mt-1">Adjust models and detection settings.</p>
						</div>
						<ChevronRightIcon class="mt-0.5 size-4 shrink-0 text-muted-foreground" />
					</a>
				</nav>
			</aside>
		</div>
	</section>
{/if}

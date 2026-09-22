<script lang="ts">
	import { resolve } from '$app/paths';
	import { Button } from '$lib/components/ui/button';
	let { id, label }: { id: string; label: string } = $props();
	let open = $state(false);
	let failed = $state(false);
	let version = $state(0);
	function release(node: HTMLImageElement) {
		return {
			destroy() {
				node.src = 'data:,';
			}
		};
	}
</script>

<div class="flex flex-col gap-3">
	<Button
		type="button"
		variant="outline"
		onclick={() => {
			open = !open;
			failed = false;
		}}>{open ? 'Hide live picture' : 'Show live picture'}</Button
	>
	{#if open}
		{#key version}<img
				use:release
				src={resolve(`/cameras/${id}/preview`)}
				alt={`${label} live picture`}
				onerror={() => (failed = true)}
				class="aspect-video w-full rounded-md bg-muted object-contain"
			/>{/key}
		{#if failed}<p role="status" class="text-sm text-muted-foreground">
				The live picture is unavailable. Check the camera connection in Camera settings.
			</p>
		{:else}<p class="text-sm text-muted-foreground">
				If the picture freezes or disappears, retry the live picture.
			</p>{/if}
		<Button
			type="button"
			variant="outline"
			onclick={() => {
				failed = false;
				version += 1;
			}}>Retry picture</Button
		>
	{/if}
</div>

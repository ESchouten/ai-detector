<script lang="ts">
	import { badgeHue } from '$lib/badge-colors';
	// The same hue as the detector's pills and its boxes on the live picture.
	let { seed }: { seed: string } = $props();
</script>

<span
	class="size-2.5 shrink-0 rounded-full"
	style={`background: oklch(0.72 0.14 ${badgeHue(seed)})`}
	aria-hidden="true"
></span>

<script lang="ts">
	import { Badge } from '$lib/components/ui/badge';
	import { badgeHue } from '$lib/badge-colors';
	let { label, seed = label }: { label: string; seed?: string } = $props();
</script>

<Badge
	variant="tinted"
	style={`--badge-hue: ${badgeHue(seed)}`}
	class="max-w-full text-left whitespace-normal">{label}</Badge
>

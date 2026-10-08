<script lang="ts" module>
	export type PillTone = 'neutral' | 'ok' | 'warn' | 'bad' | 'category';
	const tones: Record<PillTone, string> = {
		neutral: 'bg-secondary text-secondary-foreground',
		ok: 'bg-success text-success-foreground',
		warn: 'bg-warning text-warning-foreground',
		bad: 'bg-danger text-danger-foreground',
		category: 'bg-category text-category-foreground'
	};
</script>

<script lang="ts">
	import type { Snippet } from 'svelte';
	import { Badge } from '$lib/components/ui/badge';
	import { badgeHue } from '$lib/badge-colors';
	import { cn } from '$lib/utils';

	// Status and category colors are the application's own; the shadcn badge stays as published.
	let {
		tone = 'neutral',
		seed,
		class: className,
		children,
		...rest
	}: {
		tone?: PillTone;
		/** Category pills take a stable color from this name. */
		seed?: string;
		class?: string;
		children: Snippet;
		title?: string;
		role?: string;
	} = $props();
</script>

<Badge
	variant="outline"
	style={tone === 'category' && seed ? `--badge-hue: ${badgeHue(seed)}` : undefined}
	class={cn(
		'max-w-full border-transparent text-left font-medium whitespace-normal',
		tones[tone],
		className
	)}
	{...rest}
>
	{@render children()}
</Badge>

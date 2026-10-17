<script lang="ts">
	import { Moon, Sun } from '@lucide/svelte';
	import { toggleMode } from 'mode-watcher';
	import { Button } from '$lib/components/ui/button';
</script>

<Button variant="ghost" size="icon-sm" onclick={toggleMode} aria-label="Switch light or dark theme">
	<Sun class="dark:hidden" aria-hidden="true" />
	<Moon class="hidden dark:block" aria-hidden="true" />
</Button>

<script lang="ts">
	import BrandMark from '$lib/components/brand-mark.svelte';
	import PageError from '$lib/components/page-error.svelte';
</script>

<!-- Shown without the application's frame, which itself needs settings that could not be read. -->
<main class="mx-auto flex min-h-dvh max-w-2xl flex-col justify-center gap-6 p-6">
	<BrandMark class="size-11 rounded-xl [&>svg]:size-6" />
	<PageError />
</main>

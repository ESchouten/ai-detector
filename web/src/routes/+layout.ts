import { browser } from '$app/environment';
import { loadLocale } from 'wuchale/load-utils';
import { isLocale, SOURCE_LOCALE } from '$lib/locales';
// Registers the catalogs that loadLocale fills.
import '../locales/main.loader.svelte.js';
import '../locales/js.loader.js';
import type { LayoutLoad } from './$types';

/**
 * The server renders each page in the installation's language and names it on <html>.
 * Load the same catalog before the browser takes over, so no text changes or flickers.
 */
export const load: LayoutLoad = async () => {
	if (!browser) return;
	const language = document.documentElement.lang;
	await loadLocale(isLocale(language) ? language : SOURCE_LOCALE);
};

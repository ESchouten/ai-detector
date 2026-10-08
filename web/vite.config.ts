import tailwindcss from '@tailwindcss/vite';
import devtoolsJson from 'vite-plugin-devtools-json';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig, type PluginOption } from 'vite';
import { wuchale } from 'wuchale/vite';

const buildTarget = process.env.AI_DETECTOR_WEB_TARGET?.trim().toLowerCase() || 'node';

export default defineConfig({
	define: {
		__AI_DETECTOR_WEB_TARGET__: JSON.stringify(buildTarget)
	},
	server: {
		allowedHosts: ['.local']
	},
	// Wuchale replaces interface text with catalog lookups before Svelte compiles it.
	// Its hot-update hook returns `false` to skip a file, which Vite's types do not describe.
	plugins: [tailwindcss(), wuchale() as PluginOption, sveltekit(), devtoolsJson()]
});

import nodeAdapter from '@sveltejs/adapter-node';
import exeAdapter from '@jesterkit/exe-sveltekit';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

const buildTarget = process.env.AI_DETECTOR_WEB_TARGET?.trim().toLowerCase() || 'node';
const adapter =
	buildTarget === 'node'
		? nodeAdapter()
		: exeAdapter({
				binaryName: 'ai-detector-web',
				target: buildTarget,
				runtimeDirectory: 'desktop',
				compileArgs: buildTarget.startsWith('windows-')
					? [
							'--windows-hide-console',
							'--windows-icon=../distribution/windows/artwork/app.ico',
							'--windows-title=AI Detector',
							'--windows-publisher=AI Detector',
							'--windows-description=AI Detector camera monitoring',
							`--windows-version=${process.env.APP_VERSION ?? '0.0.0'}`
						]
					: []
			});

/** @type {import('@sveltejs/kit').Config} */
const config = {
	// Consult https://svelte.dev/docs/kit/integrations
	// for more information about preprocessors
	preprocess: vitePreprocess(),
	compilerOptions: {
		experimental: {
			async: true
		}
	},
	kit: {
		adapter,
		experimental: {
			remoteFunctions: true
		}
	}
};

export default config;

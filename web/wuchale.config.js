// @ts-check
import { adapter as svelte, svelteKitDefaultHeuristic } from '@wuchale/svelte';
import {
	adapter as vanilla,
	defaultArgs,
	pluralPattern,
	Transformer
} from 'wuchale/adapter-vanilla';
import { defineConfig } from 'wuchale';
import { getFuncNameNested } from 'wuchale/adapter-utils';
import { LOCALES } from './src/lib/locales.ts';

// Wuchale leaves `throw` statements alone, but this application shows thrown messages to the
// person using it (a failed save, a camera that rejects its login), so they are translated too.
Transformer.prototype.visitThrowStatement = function (node) {
	return this.visit(node.argument);
};

/** `plural(count, ['# camera', '# cameras'])` and `language()` receive the catalog's language. */
const patterns = [
	pluralPattern,
	{ name: 'language', args: /** @type {['locale']} */ (['locale']) }
];

/**
 * Text that looks like a sentence but is not shown to anyone: header names, file names,
 * and lines written to the logs, which stay in English for support.
 * @param {import('wuchale').Text} text
 */
function technical(text) {
	if (text.path.at(-1)?.type === 'element') return false;
	const body = Array.isArray(text.body) ? text.body.join(' ') : text.body;
	// Content-Type, README.txt, HOME=/tmp; and names such as ArrowLeft or ETag.
	if (!/\s/.test(body) && (/[-_./=:]/.test(body) || /^[A-Z][a-z]*[A-Z][A-Za-z]*$/.test(body)))
		return true;
	// A log line: a timestamp, then text, ending the line.
	if (/^\{0\} [^]*\n$/.test(body)) return true;
	return text.path.some(
		(scope) => scope.type === 'call' && /(^|\.)(log\.append|webLog\.\w+)$/.test(scope.name)
	);
}

/**
 * Where a catalog is looked up. In a component, once at the top, reactively. In a module
 * (`.svelte.ts`, `<script module>`) text inside a function or method looks it up when that
 * runs, so the server answers each request in its own language. Wuchale does the latter for
 * `.svelte.js` functions only, and would otherwise place `$derived` inside class methods.
 * @param {import('wuchale').Text['path']} path
 * @param {string} file
 * @param {{ module: boolean }} context
 */
function lookup(path, file, { module }) {
	if (module || /\.svelte\.[jt]s$/.test(file)) {
		const callable = path.some((scope) => ['function', 'funcexpr', 'method'].includes(scope.type));
		return { init: !callable, reactive: !callable };
	}
	return { init: getFuncNameNested(path)[0] == null ? true : null, reactive: true };
}

export default defineConfig({
	locales: [...LOCALES],
	// Translations are written and reviewed by people (see src/locales/README.md); nothing is
	// sent to a translation service because an API key happens to be set.
	ai: null,
	adapters: {
		main: svelte({
			loader: 'custom',
			patterns,
			heuristic: (text, file) => (technical(text) ? false : svelteKitDefaultHeuristic(text, file)),
			runtime: {
				initReactive: (path, file, context) => lookup(path, file, context).init,
				useReactive: (path, file, context) => lookup(path, file, context).reactive
			}
		}),
		js: vanilla({
			loader: 'custom',
			patterns,
			files: {
				include: ['src/**/*.{js,ts}'],
				ignore: [
					'src/**/*.svelte.{js,ts}',
					'src/**/*.d.ts',
					'src/lib/generated/**',
					// Vendor components raise developer errors here; their visible text is in .svelte files.
					'src/lib/components/ui/**'
				]
			},
			heuristic: (text, file) => (technical(text) ? false : defaultArgs.heuristic(text, file))
		})
	}
});

// Dependency-cruiser's resolver does not resolve SvelteKit's inherited $lib alias.
// This is resolver configuration only; the application is built with Vite.
import path from 'node:path';

export default {
	resolve: {
		alias: { $lib: path.resolve(import.meta.dirname, '../src/lib') },
		extensionAlias: { '.js': ['.ts', '.d.ts', '.js'] }
	}
};

/** @type {import('dependency-cruiser').IConfiguration} */
module.exports = {
	forbidden: [
		{
			name: 'no-application-cycles',
			severity: 'error',
			comment: 'Feature code must have an unambiguous dependency direction.',
			from: { path: '^(src/|desktop/)', pathNot: '^src/lib/components/ui/' },
			to: { circular: true }
		},
		{
			name: 'desktop-runtime-does-not-import-web-features',
			severity: 'error',
			from: { path: '^desktop/' },
			to: { path: '^src/' }
		},
		{
			name: 'server-does-not-import-presentation',
			severity: 'error',
			from: { path: '^src/lib/server/' },
			to: { path: '^src/(routes/|lib/(remote|components)/)' }
		},
		{
			name: 'remote-handlers-use-server-services',
			severity: 'error',
			from: { path: '^src/lib/remote/' },
			to: { path: '^src/(routes/|lib/remote/)' }
		},
		{
			name: 'browser-code-does-not-import-server',
			severity: 'error',
			from: { path: '^src/(lib/(components|hooks)/|routes/.*\\.svelte$)' },
			to: { path: '^(src/lib/server/|node:)' }
		},
		{
			name: 'browser-and-remote-code-do-not-import-node',
			severity: 'error',
			from: { path: '^src/(lib/(remote|components|hooks)/|routes/.*\\.svelte$)' },
			to: { dependencyTypes: ['core'] }
		},
		{
			name: 'shared-models-stay-independent',
			severity: 'error',
			from: { path: '^src/lib/((schema|runtime|detections|live-preview)\\.ts$|generated/)' },
			to: {
				pathNot:
					'^src/lib/((schema|runtime|detections|live-preview)\\.ts$|generated/)|(?:^|/)node_modules/valibot/'
			}
		},
		{
			name: 'resolve-project-imports',
			severity: 'error',
			from: {},
			to: {
				couldNotResolve: true,
				path: '^(src/|\\$lib/|\\.\\.?/)',
				// SvelteKit/Vite resolve these virtual imports during check/build.
				pathNot: '^(\\$app/|\\$env/)|\\$types$|\\?worker$'
			}
		}
	],
	options: {
		doNotFollow: { path: 'node_modules' },
		tsConfig: { fileName: 'tsconfig.json' },
		webpackConfig: { fileName: 'tools/dependency-resolution.mjs' },
		tsPreCompilationDeps: true,
		exclude: { path: '\\.svelte-kit/' },
		enhancedResolveOptions: {
			extensions: ['.ts', '.js', '.svelte', '.json'],
			exportsFields: ['exports'],
			conditionNames: ['svelte', 'import', 'node', 'default']
		}
	}
};

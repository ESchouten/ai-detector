import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { cp, mkdir, mkdtemp, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';

const web = fileURLToPath(new URL('..', import.meta.url));
const command = path.join(web, 'node_modules/dependency-cruiser/bin/dependency-cruiser.mjs');
const exec = promisify(execFile);

test('architecture rules reject cycles, reverse dependencies, aliases and dynamic imports', async (t) => {
	const directory = await mkdtemp(path.join(tmpdir(), 'ai-architecture-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	await cp(
		path.join(web, '.dependency-cruiser.cjs'),
		path.join(directory, '.dependency-cruiser.cjs')
	);
	await cp(path.join(web, 'tools'), path.join(directory, 'tools'), { recursive: true });
	await symlink(path.join(web, 'node_modules'), path.join(directory, 'node_modules'), 'junction');
	await writeFile(
		path.join(directory, 'tsconfig.json'),
		JSON.stringify({ compilerOptions: { target: 'ESNext', module: 'ESNext' }, include: ['src'] })
	);
	const files = {
		'src/lib/server/database.ts': "import '$lib/remote/save.remote'; export const result = 1;",
		'src/lib/remote/save.remote.ts':
			"import 'node:fs'; import './other.remote'; export const save = true;",
		'src/lib/remote/other.remote.ts': 'export const other = true;',
		'src/lib/schema.ts':
			"import type { Runtime } from './server/runtime'; export type Model = Runtime;",
		'src/lib/server/runtime.ts': 'export interface Runtime { name: string }',
		'src/lib/components/Async.svelte':
			'<script lang="ts">const service = await import("$lib/server/database");</script><p>{service.result}</p>',
		'src/lib/a.ts': "import './b'; export const a = 1;",
		'src/lib/b.ts': "import './a'; export const b = 2;",
		'src/lib/missing.ts': "import './does-not-exist';"
	};
	for (const [file, content] of Object.entries(files)) {
		await mkdir(path.dirname(path.join(directory, file)), { recursive: true });
		await writeFile(path.join(directory, file), content);
	}
	const { stdout } = await exec(
		process.execPath,
		[command, 'src', '--config', '.dependency-cruiser.cjs', '--output-type', 'json'],
		{ cwd: directory }
	);
	const graph = JSON.parse(stdout);
	const violated = new Set(
		graph.summary.violations.map((entry: { rule: { name: string } }) => entry.rule.name)
	);
	assert.deepEqual(
		[...violated].sort(),
		[
			'no-application-cycles',
			'server-does-not-import-presentation',
			'remote-handlers-use-server-services',
			'browser-code-does-not-import-server',
			'browser-and-remote-code-do-not-import-node',
			'shared-models-stay-independent',
			'resolve-project-imports'
		].sort()
	);
	const component = graph.modules.find(
		(module: { source: string }) => module.source === 'src/lib/components/Async.svelte'
	);
	assert.ok(
		component.dependencies.some(
			(dependency: { resolved: string }) => dependency.resolved === 'src/lib/server/database.ts'
		)
	);
	// Each fixture source must be analyzed, including Svelte and standalone type files.
	assert.deepEqual(
		graph.modules
			.filter((module: { source: string }) => module.source in files)
			.map((module: { source: string }) => module.source)
			.sort(),
		Object.keys(files).sort()
	);
});

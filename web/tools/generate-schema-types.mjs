import { existsSync } from 'node:fs';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { compileFromFile } from 'json-schema-to-typescript';
import { resolveConfig } from 'prettier';

const { values } = parseArgs({ options: { check: { type: 'boolean', default: false } } });
const directory = new URL('../src/lib/generated/', import.meta.url);
if (!values.check) await mkdir(directory, { recursive: true });

for (const name of ['config', 'metadata']) {
	const source = new URL(`../../config/${name}.schema.json`, import.meta.url);
	const output = new URL(`${name}.d.ts`, directory);
	const content = await compileFromFile(fileURLToPath(source), {
		bannerComment: `/** Generated from config/${name}.schema.json. Run pnpm schema:generate; do not edit. */`,
		style: await resolveConfig(fileURLToPath(output))
	});
	if (values.check) {
		const current = existsSync(output) ? await readFile(output, 'utf8') : '';
		if (current !== content) {
			console.error(`${name}.d.ts is out of date. Run pnpm schema:generate.`);
			process.exitCode = 1;
		}
	} else {
		await writeFile(output, content);
	}
}

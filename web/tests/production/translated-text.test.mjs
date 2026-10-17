// Run against the built server, whose code still carries the translation tool's own names.
import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { test } from 'node:test';
import { Linter } from 'eslint';

const chunks = path.resolve(import.meta.dirname, '../../build/server/chunks');

// The translation tool replaces each text by a call on a runtime it defines at the top of the
// function the text is in. Inside a nested function it sometimes leaves the definition out, and
// reading that text then throws: a camera that refused its login stayed on Connecting, and a
// failed live preview stopped the whole server. Components are in the server build too.
test('every translated text has the runtime that reads it', async () => {
	const linter = new Linter();
	const missing = [];
	for (const name of await readdir(chunks)) {
		if (!name.endsWith('.js')) continue;
		const code = await readFile(path.join(chunks, name), 'utf8');
		if (!code.includes('_w_runtime_')) continue;
		for (const message of linter.verify(code, {
			languageOptions: { ecmaVersion: 'latest', sourceType: 'module' },
			rules: { 'no-undef': 'error' }
		}))
			if (message.message.includes('_w_runtime_')) missing.push(`${name}:${message.line}`);
	}
	assert.deepEqual(missing, []);
});

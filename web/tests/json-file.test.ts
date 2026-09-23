import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readdir, rm, stat, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test, type TestContext } from 'node:test';
import { readJson, writeJson } from '../src/lib/server/json-file.ts';

async function fixture(t: TestContext) {
	const directory = await mkdtemp(path.join(tmpdir(), 'ai-settings-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	return directory;
}

test('settings replacements remain private and leave only the completed JSON file', async (t) => {
	const directory = await fixture(t);
	const file = path.join(directory, 'settings', 'runtime.json');
	assert.equal(await readJson(file), null);
	await writeJson(file, { enabled: false });
	await writeJson(file, { enabled: true, label: 'Mañana' });
	assert.deepEqual(await readJson(file), { enabled: true, label: 'Mañana' });
	assert.deepEqual(await readdir(path.dirname(file)), ['runtime.json']);
	if (process.platform !== 'win32') assert.equal((await stat(file)).mode & 0o777, 0o600);
});

test('a failed replacement preserves the destination, cleans staging files and releases its queue', async (t) => {
	const directory = await fixture(t);
	const file = path.join(directory, 'runtime.json');
	await mkdir(file);
	await writeFile(path.join(file, 'existing'), 'keep');
	await assert.rejects(writeJson(file, { enabled: true }));
	assert.deepEqual(await readdir(file), ['existing']);
	assert.deepEqual(await readdir(directory), ['runtime.json']);
	await rm(file, { recursive: true });
	await writeJson(file, { enabled: false });
	assert.deepEqual(await readJson(file), { enabled: false });
});

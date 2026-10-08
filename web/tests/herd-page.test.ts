import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test, type TestContext } from 'node:test';
import { IdentityCatalog } from '../src/lib/server/identity-catalog.ts';
import { readHerdPage } from '../src/lib/server/herd-page.ts';
import { webLog } from '../src/lib/server/web-log.ts';

async function fixture(t: TestContext) {
	const root = await mkdtemp(path.join(tmpdir(), 'herd-page-'));
	t.after(() => rm(root, { recursive: true, force: true }));
	const herd = new IdentityCatalog(root);
	await mkdir(herd.directory, { recursive: true });
	return { root, herd, file: path.join(herd.directory, 'catalog.json') };
}

test('a new installation has an available empty herd without creating a catalog', async (t) => {
	const { herd, file } = await fixture(t);
	const catalog = await readHerdPage(herd);
	assert.ok(catalog);
	assert.equal(catalog.revision, 0);
	assert.deepEqual(catalog.identities, []);
	await assert.rejects(readFile(file), { code: 'ENOENT' });
});

test('unreadable enrollment is visible as unavailable, logged, and never replaced', async (t) => {
	const { root, herd, file } = await fixture(t);
	await webLog.initialize(root, '1.2.3');
	for (const contents of ['{broken', '{"version":99}']) {
		await writeFile(file, contents);
		assert.equal(await readHerdPage(herd), null);
		assert.equal(await readFile(file, 'utf8'), contents);
	}
	await webLog.flush();
	assert.match(await webLog.read(), /Could not read the saved herd/);
	assert.match(await webLog.read(), /SyntaxError/);
	await writeFile(file, '{"version":1,"revision":4,"identities":[]}');
	assert.equal((await readHerdPage(herd))?.revision, 4);
});

test('unrelated filesystem failures are not mistaken for an empty or corrupt herd', async (t) => {
	const { herd, file } = await fixture(t);
	await mkdir(file);
	await assert.rejects(readHerdPage(herd), { code: 'EISDIR' });
});

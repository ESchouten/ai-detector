import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test, type TestContext } from 'node:test';
import { unzipSync } from 'fflate';
import { backupSettings } from '../src/lib/server/settings-backup.ts';
import { IdentityCatalog } from '../src/lib/server/identity-catalog.ts';
import { ConfigurationStore } from '../src/lib/server/configuration/store.ts';
import { InstallationImport } from '../src/lib/server/installation-import/service.ts';
import { writeJson } from '../src/lib/server/json-file.ts';

const confirmed = 'a'.repeat(32);
const pending = 'b'.repeat(32);

function store(root: string) {
	return new ConfigurationStore({
		config: path.join(root, 'config.json'),
		app: path.join(root, 'app.json')
	});
}

async function addPhoto(herd: IdentityCatalog, id: string) {
	await writeJson(path.join(herd.directory, 'sightings', `${id}.json`), {
		version: 1,
		id,
		image: id,
		source: '1'.repeat(64),
		captured_at: '2026-10-03T10:00:00Z',
		track_id: 1,
		gallery_revision: 0,
		identity: { id: null, name: null, similarity: null }
	});
	await mkdir(path.dirname(herd.image(id)!), { recursive: true });
	await writeFile(herd.image(id)!, Buffer.from([0xff, 0xd8, 0x01, 0xff, 0xd9]));
}

async function fixture(t: TestContext) {
	const directory = await mkdtemp(path.join(tmpdir(), 'herd-backup-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	const source = path.join(directory, 'source');
	const destination = path.join(directory, 'destination');
	await mkdir(source);
	await mkdir(destination);
	const configuration = store(source);
	await configuration.replace({ config: { detectors: [] }, app: {} });
	const herd = new IdentityCatalog(source);
	await addPhoto(herd, confirmed);
	await addPhoto(herd, pending);
	await herd.assign(0, confirmed, null, 'Cow 142');
	await writeFile(path.join(herd.directory, 'embeddings.sqlite'), 'disposable cache');
	return { directory, source, destination, configuration, herd };
}

test('settings ZIP restores confirmed herd photos and preserves later correction, without caches or pending photos', async (t) => {
	const { directory, destination, configuration, herd } = await fixture(t);
	const original = await herd.snapshot();
	const response = await backupSettings(
		configuration,
		herd,
		new Request('http://localhost/setup/backup')
	);
	const entries = unzipSync(new Uint8Array(await response.arrayBuffer()));
	assert.deepEqual(
		Object.keys(entries).sort(),
		[
			'README.txt',
			'app.json',
			'config.json',
			'identities/catalog.json',
			`identities/images/${confirmed}.jpg`,
			`identities/sightings/${confirmed}.json`
		].sort()
	);
	assert.deepEqual(
		JSON.parse(Buffer.from(entries['identities/catalog.json']).toString()),
		original.catalog
	);
	assert.deepEqual(
		Buffer.from(entries[`identities/images/${confirmed}.jpg`]),
		await readFile(herd.image(confirmed)!)
	);
	const extracted = path.join(directory, 'extracted');
	await mkdir(extracted);
	for (const [name, content] of Object.entries(entries)) {
		await mkdir(path.dirname(path.join(extracted, name)), { recursive: true });
		await writeFile(path.join(extracted, name), content);
	}
	const importer = new InstallationImport(destination, store(destination));
	const summary = await importer.inspect(extracted);
	assert.ok(summary.notes.includes('Confirmed herd: 1 cow, 1 photo.'));
	await importer.start(summary.id, false);
	await importer.settled();
	assert.equal((await importer.getStatus()).phase, 'complete');
	const restored = new IdentityCatalog(destination);
	assert.deepEqual(await restored.snapshot(), original);
	assert.deepEqual((await restored.list()).review, []);
	const cow = original.catalog.identities[0];
	await restored.removeExample(1, cow.id, confirmed);
	assert.equal((await restored.list()).review[0].id, confirmed);
	await restored.assign(2, confirmed, cow.id, '');
	assert.equal((await restored.list()).identities[0].name, 'Cow 142');
	assert.deepEqual((await herd.snapshot()).catalog, original.catalog);
});

test('import selects only confirmed herd files from a complete old data directory', async (t) => {
	const { source, destination, herd } = await fixture(t);
	const importer = new InstallationImport(destination, store(destination));
	const summary = await importer.inspect(source);
	await importer.start(summary.id, true);
	await importer.settled();
	assert.equal((await importer.getStatus()).phase, 'complete');
	const restored = new IdentityCatalog(destination);
	assert.deepEqual(await restored.snapshot(), await herd.snapshot());
	await assert.rejects(readFile(restored.image(pending)!), { code: 'ENOENT' });
	await assert.rejects(readFile(path.join(restored.directory, 'embeddings.sqlite')), {
		code: 'ENOENT'
	});
});

test('missing or invalid confirmed evidence cannot produce a misleading settings backup or import', async (t) => {
	const { source, destination, configuration, herd } = await fixture(t);
	await rm(herd.image(confirmed)!);
	await assert.rejects(
		backupSettings(configuration, herd, new Request('http://localhost/setup/backup')),
		{ code: 'ENOENT' }
	);
	await assert.rejects(new InstallationImport(destination, store(destination)).inspect(source), {
		code: 'ENOENT'
	});
	await addPhoto(herd, confirmed);
	await writeJson(path.join(herd.directory, 'sightings', `${confirmed}.json`), {
		version: 1,
		id: confirmed
	});
	await assert.rejects(
		new InstallationImport(destination, store(destination)).inspect(source),
		/missing or invalid details/
	);
	await assert.rejects(readFile(path.join(destination, 'config.json')), { code: 'ENOENT' });
});

test('fresh-setup import refuses an existing herd, including one created after inspection', async (t) => {
	const { source, destination } = await fixture(t);
	const importer = new InstallationImport(destination, store(destination));
	const summary = await importer.inspect(source);
	const live = new IdentityCatalog(destination);
	await addPhoto(live, pending);
	await live.assign(0, pending, null, 'Existing cow');
	const before = await live.snapshot();
	await assert.rejects(importer.inspect(source), /already has a herd/);
	await importer.start(summary.id, false);
	await importer.settled();
	assert.equal((await importer.getStatus()).phase, 'failed');
	assert.match((await importer.getStatus()).message!, /already has a herd/);
	assert.deepEqual(await live.snapshot(), before);
	await assert.rejects(readFile(path.join(destination, 'config.json')), { code: 'ENOENT' });
});

test(
	'linked herd references cannot escape the selected backup or installation',
	{ skip: process.platform === 'win32' },
	async (t) => {
		const { directory, source, destination, configuration, herd } = await fixture(t);
		const outside = path.join(directory, 'private.jpg');
		await writeFile(outside, 'not part of the herd');
		await rm(herd.image(confirmed)!);
		await symlink(outside, herd.image(confirmed)!);
		await assert.rejects(
			backupSettings(configuration, herd, new Request('http://localhost/setup/backup')),
			/symbolic link/
		);
		await assert.rejects(
			new InstallationImport(destination, store(destination)).inspect(source),
			/symbolic link/
		);
		assert.equal(await readFile(outside, 'utf8'), 'not part of the herd');
	}
);

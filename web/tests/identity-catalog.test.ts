import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test, type TestContext } from 'node:test';
import { IdentityCatalog, HerdError } from '../src/lib/server/identity-catalog.ts';

const photoA = 'a'.repeat(32);
const photoB = 'b'.repeat(32);
const photoC = 'c'.repeat(32);

async function fixture(t: TestContext) {
	const root = await mkdtemp(path.join(tmpdir(), 'herd-test-'));
	t.after(() => rm(root, { recursive: true, force: true }));
	const catalog = new IdentityCatalog(root);
	await mkdir(path.join(catalog.directory, 'sightings'), { recursive: true });
	await mkdir(path.join(catalog.directory, 'images'), { recursive: true });
	async function sighting(
		id: string,
		capturedAt = '2026-10-03T10:00:00',
		suggestion?: { id: string; name: string; revision?: number | null },
		followed?: { run: string; track: number }
	) {
		await writeFile(
			path.join(catalog.directory, 'sightings', `${id}.json`),
			JSON.stringify({
				version: 1,
				id,
				image: id,
				source: '1'.repeat(64),
				captured_at: capturedAt,
				run: followed?.run,
				track_id: followed?.track ?? 2,
				gallery_revision: suggestion?.revision,
				identity: {
					id: suggestion?.id ?? null,
					name: suggestion?.name ?? null,
					similarity: suggestion ? 0.95 : null
				}
			})
		);
		await writeFile(catalog.image(id)!, 'test image');
	}
	return { catalog, sighting };
}

test('farmer confirms varied examples, corrects a mistake, and returns removed cows to review', async (t) => {
	const { catalog, sighting } = await fixture(t);
	assert.deepEqual(await catalog.list(), {
		version: 1,
		revision: 0,
		identities: [],
		review: [],
		unavailable: 0,
		full: false
	});
	await sighting(photoA);
	await sighting(photoB);
	await catalog.assign(0, photoA, null, '  Cow 142  ');
	let data = await catalog.list();
	const cow = data.identities[0];
	assert.equal(cow.name, 'Cow 142');
	assert.equal(data.review[0].id, photoB);
	await catalog.assign(1, photoB, cow.id, '');
	await catalog.rename(2, cow.id, '142');
	await catalog.removeExample(3, cow.id, photoA);
	data = await catalog.list();
	assert.equal(data.identities[0].name, '142');
	assert.deepEqual(data.identities[0].samples, [photoB]);
	assert.deepEqual(
		data.review.map((item) => item.id),
		[photoA]
	);
	await catalog.removeCow(4, cow.id);
	data = await catalog.list();
	assert.equal(data.revision, 5);
	assert.equal(data.identities.length, 0);
	assert.equal(data.review.length, 2);
	assert.equal(await readFile(catalog.image(photoA)!, 'utf8'), 'test image');
});

test('concurrent and stale edits cannot overwrite another farmer confirmation', async (t) => {
	const { catalog, sighting } = await fixture(t);
	await sighting(photoA);
	await sighting(photoB);
	const changes = await Promise.allSettled([
		catalog.assign(0, photoA, null, 'First'),
		catalog.assign(0, photoB, null, 'Second')
	]);
	assert.equal(changes[0].status, 'fulfilled');
	assert.equal(changes[1].status, 'rejected');
	if (changes[1].status === 'rejected') assert.equal(changes[1].reason.status, 409);
	const data = await catalog.list();
	assert.equal(data.identities.length, 1);
	await catalog.assign(1, photoB, null, 'Second');
	assert.equal((await catalog.list()).identities.length, 2);
});

test('moving a confirmed example changes ownership in one revision and preserves its evidence', async (t) => {
	const { catalog, sighting } = await fixture(t);
	await sighting(photoA);
	await sighting(photoB);
	await catalog.assign(0, photoA, null, 'Bella');
	await catalog.assign(1, photoB, null, 'Daisy');
	const [bella, daisy] = (await catalog.list()).identities;
	const original = await catalog.snapshot();

	await catalog.assign(2, photoA, daisy.id, '', bella.id);

	const data = await catalog.list();
	assert.equal(data.revision, 3);
	assert.deepEqual(
		data.identities.map((cow) => cow.samples),
		[[], [photoB, photoA]]
	);
	assert.equal(data.review.length, 0);
	assert.equal(await readFile(catalog.image(photoA)!, 'utf8'), 'test image');
	assert.deepEqual((await catalog.snapshot()).sightings, original.sightings.toReversed());

	await catalog.assign(3, photoA, null, 'Clover', daisy.id);
	const moved = await catalog.list();
	assert.equal(moved.revision, 4);
	assert.deepEqual(moved.identities.find((cow) => cow.name === 'Clover')?.samples, [photoA]);
	assert.deepEqual(moved.identities.find((cow) => cow.id === daisy.id)?.samples, [photoB]);
});

test('invalid or stale photo corrections leave the original owner and revision intact', async (t) => {
	const { catalog, sighting } = await fixture(t);
	await sighting(photoA);
	await sighting(photoB);
	await sighting(photoC);
	await catalog.assign(0, photoA, null, 'Bella');
	await catalog.assign(1, photoB, null, 'Daisy');
	const original = await catalog.list();
	const [bella, daisy] = original.identities;

	await assert.rejects(catalog.assign(1, photoA, daisy.id, '', bella.id), { status: 409 });
	await assert.rejects(catalog.assign(2, photoA, null, 'Clover', daisy.id), /no longer belongs/);
	await assert.rejects(catalog.assign(2, photoC, daisy.id, '', bella.id), /no longer belongs/);
	await assert.rejects(catalog.assign(2, photoA, bella.id, '', bella.id), /different cow/);
	await assert.rejects(catalog.assign(2, photoA, null, '', bella.id), /name or tag number/);
	await assert.rejects(catalog.assign(2, photoA, null, 'daisy', bella.id), /must be unique/);
	await assert.rejects(catalog.assign(2, photoA, 'f'.repeat(32), '', bella.id), /cow was removed/);
	assert.deepEqual(await catalog.list(), original);
});

test('rejects duplicate labels, confirmed photos, and invalid names without changing the catalogue', async (t) => {
	const { catalog, sighting } = await fixture(t);
	await sighting(photoA);
	await sighting(photoB);
	await catalog.assign(0, photoA, null, 'Daisy');
	await assert.rejects(catalog.assign(1, photoB, null, 'daisy'), /must be unique/);
	await assert.rejects(catalog.assign(1, photoA, null, 'Another'), /already been confirmed/);
	for (const name of ['', '   ', 'x'.repeat(81)])
		await assert.rejects(catalog.assign(1, photoB, null, name), /name or tag number/);
	assert.equal((await catalog.list()).revision, 1);
});

test('discard removes only pending photos, and IDs cannot escape the image directory', async (t) => {
	const { catalog, sighting } = await fixture(t);
	await sighting(photoA);
	await sighting(photoB);
	await catalog.assign(0, photoA, null, 'Daisy');
	await assert.rejects(catalog.discard(1, photoA), /confirmed example/);
	await catalog.discard(1, photoB);
	assert.equal((await catalog.list()).review.length, 0);
	await assert.rejects(readFile(catalog.image(photoB)!), { code: 'ENOENT' });
	for (const id of ['../config', 'A'.repeat(32), 'abc.jpg', '']) {
		assert.equal(catalog.image(id), null);
		await assert.rejects(catalog.discard(2, id), HerdError);
	}
	assert.equal(await readFile(catalog.image(photoA)!, 'utf8'), 'test image');
});

test('bad sightings do not hide healthy photos; a corrupt catalogue cannot be overwritten', async (t) => {
	const { catalog, sighting } = await fixture(t);
	await sighting(photoA, '2026-10-03T10:00:00');
	await sighting(photoB, '2026-10-03T11:00:00');
	await writeFile(path.join(catalog.directory, 'sightings', `${photoC}.json`), '{broken');
	const data = await catalog.list();
	assert.deepEqual(
		data.review.map((item) => item.id),
		[photoB, photoA]
	);
	assert.equal(data.unavailable, 1);
	await assert.rejects(catalog.assign(0, photoC, null, 'Cow'), /no longer available/);
	await writeFile(path.join(catalog.directory, 'catalog.json'), '{"version":99}');
	await assert.rejects(catalog.assign(0, photoA, null, 'Cow'), /herd file is invalid/);
	assert.equal(
		await readFile(path.join(catalog.directory, 'catalog.json'), 'utf8'),
		'{"version":99}'
	);
});

test('says when so many photos wait that the detector takes no new ones', async (t) => {
	const { catalog, sighting } = await fixture(t);
	const waiting = Array.from({ length: 199 }, (_, index) => index.toString(16).padStart(32, '0'));
	await Promise.all(waiting.map((id) => sighting(id)));
	assert.equal((await catalog.list()).full, false);
	// The detector counts a photo it wrote whether or not this application can read it.
	await writeFile(path.join(catalog.directory, 'sightings', `${photoC}.json`), '{broken');
	assert.equal((await catalog.list()).full, true);
	await catalog.discard(0, waiting[0]);
	assert.equal((await catalog.list()).full, false);
});

test('bounds enrollment without losing existing reference photos', async (t) => {
	const { catalog, sighting } = await fixture(t);
	await sighting(photoA);
	const cowId = 'f'.repeat(32);
	const samples = Array.from({ length: 1000 }, (_, index) => index.toString(16).padStart(32, '0'));
	await writeFile(
		path.join(catalog.directory, 'catalog.json'),
		JSON.stringify({
			version: 1,
			revision: 7,
			identities: [
				{ id: cowId, name: '142', samples },
				{ id: 'e'.repeat(32), name: '143', samples: [photoB] }
			]
		})
	);
	await assert.rejects(catalog.assign(7, photoA, cowId, ''), /already has 1000 examples/);
	await sighting(photoB);
	await assert.rejects(
		catalog.assign(7, photoB, cowId, '', 'e'.repeat(32)),
		/already has 1000 examples/
	);
	assert.deepEqual((await catalog.list()).identities[0].samples, samples);
	assert.deepEqual((await catalog.list()).identities[1].samples, [photoB]);
	assert.equal((await catalog.list()).revision, 7);
});

test('gallery corrections invalidate old suggestions without hiding or rewriting evidence', async (t) => {
	const { catalog, sighting } = await fixture(t);
	await sighting(photoA);
	await sighting(photoB);
	await catalog.assign(0, photoA, null, 'Bella');
	await catalog.assign(1, photoB, null, 'Daisy');
	const bella = (await catalog.list()).identities.find((cow) => cow.name === 'Bella')!;
	await sighting(photoC, '2026-10-03T10:00:00', { ...bella, revision: 2 });
	const recordPath = path.join(catalog.directory, 'sightings', `${photoC}.json`);
	const original = await readFile(recordPath, 'utf8');
	assert.equal((await catalog.list()).review[0].identity.id, bella.id);

	await catalog.removeExample(2, bella.id, photoA);

	const review = (await catalog.list()).review.find((item) => item.id === photoC)!;
	assert.deepEqual(review.identity, { id: null, name: null, similarity: 0.95 });
	assert.equal(await readFile(recordPath, 'utf8'), original);
	assert.equal(await readFile(catalog.image(photoC)!, 'utf8'), 'test image');
});

test('unversioned and unknown-revision photos remain reviewable without suggested labels', async (t) => {
	const { catalog, sighting } = await fixture(t);
	await sighting(photoA);
	await catalog.assign(0, photoA, null, 'Bella');
	const bella = (await catalog.list()).identities[0];
	await sighting(photoB, '2026-10-03T10:00:00', bella);
	await sighting(photoC, '2026-10-03T10:00:00', { ...bella, revision: null });

	const { review, unavailable } = await catalog.list();
	assert.equal(review.length, 2);
	assert.equal(unavailable, 0);
	assert.ok(review.every((item) => item.identity.id === null && item.identity.name === null));
});

test('photos of one followed animal are confirmed together, and only those', async (t) => {
	const { catalog, sighting } = await fixture(t);
	const morning = { run: 'd'.repeat(32), track: 5 };
	const [first, second, third] = ['1', '2', '3'].map((digit) => digit.repeat(32));
	await sighting(first, '2026-10-03T10:00:00', undefined, morning);
	await sighting(second, '2026-10-03T10:00:30', undefined, morning);
	await sighting(third, '2026-10-03T10:01:00', undefined, morning);
	// The same track number after a restart, another track, and a photo from before runs
	// were recorded: none of these is known to be the same animal.
	await sighting(photoA, '2026-10-03T12:00:00', undefined, { run: 'e'.repeat(32), track: 5 });
	await sighting(photoB, '2026-10-03T10:00:10', undefined, { ...morning, track: 6 });
	await sighting(photoC, '2026-10-03T10:00:20');

	const review = (await catalog.list()).review;
	const companions = Object.fromEntries(review.map((item) => [item.id, item.companions.sort()]));
	assert.deepEqual(companions[second], [first, third]);
	assert.deepEqual([companions[photoA], companions[photoB], companions[photoC]], [[], [], []]);

	await catalog.assign(0, second, null, '142', null, true);
	const data = await catalog.list();
	assert.deepEqual(data.identities[0].samples.sort(), [first, second, third]);
	assert.deepEqual(data.review.map((item) => item.id).sort(), [photoA, photoB, photoC]);

	// Alone when not asked for, and never beyond what a cow can hold.
	const afternoon = { run: 'e'.repeat(32), track: 5 };
	await sighting('4'.repeat(32), '2026-10-03T12:00:30', undefined, afternoon);
	await catalog.assign(1, photoA, null, '143');
	assert.deepEqual((await catalog.list()).identities[1].samples, [photoA]);
	const full = Array.from({ length: 999 }, (_, index) => index.toString(16).padStart(32, '0'));
	await writeFile(
		path.join(catalog.directory, 'catalog.json'),
		JSON.stringify({
			version: 1,
			revision: 2,
			identities: [{ id: 'f'.repeat(32), name: '144', samples: full }]
		})
	);
	await sighting('5'.repeat(32), '2026-10-03T12:01:00', undefined, afternoon);
	await catalog.assign(2, photoA, 'f'.repeat(32), '', null, true);
	assert.equal((await catalog.list()).identities[0].samples.length, 1000);
});

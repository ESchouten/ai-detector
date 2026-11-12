import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { test } from 'node:test';
import { IndividualsFolder, SightingMissingError } from '../src/lib/server/individuals-folder.ts';
import { temporaryDirectory } from './support/files.ts';

const id = (digit: string) => digit.repeat(32);

/** The outline of its one picture, as a segmentation model gave it. */
const outline: [number, number][] = [
	[1, 2],
	[30, 2],
	[30, 40]
];

/** A sighting as the detector publishes it. */
async function sighting(directory: string, sightingId: string, seen: string) {
	const folder = path.join(directory, 'sightings', sightingId);
	await mkdir(folder, { recursive: true });
	await writeFile(path.join(folder, 'crop-1.jpg'), 'picture');
	await writeFile(
		path.join(folder, 'sighting.json'),
		JSON.stringify({
			version: 1,
			id: sightingId,
			camera: 'c'.repeat(12),
			label: 'cow',
			track: 1,
			seen,
			event_id: 'e'.repeat(32),
			crops: 1,
			outlines: [outline]
		})
	);
}

async function groups(directory: string, ...groups: [string[], string[]][]) {
	await writeFile(
		path.join(directory, 'groups.json'),
		JSON.stringify({
			version: 1,
			model: 'f'.repeat(16),
			groups: groups.map(([sightings, names]) => ({
				sightings,
				suggestions: names.map((name, index) => ({ name, score: 0.9 - index / 10 }))
			}))
		})
	);
}

test('unnamed sightings are listed in the look-alike groups the detector made, then ungrouped ones newest first', async (t) => {
	const directory = await temporaryDirectory(t, 'individuals-');
	const folder = new IndividualsFolder(directory);
	assert.deepEqual(await folder.overview(), {
		groups: [],
		moreGroups: 0,
		unnamed: 0,
		named: [],
		namedDays: 0
	});

	await sighting(directory, id('1'), '2026-10-01T12:00:00');
	await sighting(directory, id('2'), '2026-10-01T12:05:00');
	await sighting(directory, id('3'), '2026-10-02T08:00:00');
	await sighting(directory, id('4'), '2026-10-02T09:00:00');
	await sighting(directory, id('5'), '2026-10-03T09:00:00');
	await groups(directory, [[id('1'), id('2')], ['412']], [[id('3')], []]);
	await folder.name([id('3')], '233');

	const overview = await folder.overview();
	assert.deepEqual(
		overview.groups.map((group) => [group.ids, group.suggestions, group.shown.map((s) => s.id)]),
		[
			[[id('1'), id('2')], ['412'], [id('1'), id('2')]],
			[[id('5')], [], [id('5')]],
			[[id('4')], [], [id('4')]]
		]
	);
	assert.equal(overview.unnamed, 4);
	assert.deepEqual(overview.named, [
		{
			name: '233',
			ids: [id('3')],
			shown: [{ id: id('3'), seen: '2026-10-02T08:00:00', crops: 1, outlines: [outline] }]
		}
	]);
});

test('naming writes the whole names file the detector reads, and a name can be taken off again', async (t) => {
	const directory = await temporaryDirectory(t, 'individuals-');
	const folder = new IndividualsFolder(directory);
	await sighting(directory, id('1'), '2026-10-01T12:00:00');
	await sighting(directory, id('2'), '2026-10-02T12:00:00');
	await sighting(directory, id('3'), '2026-10-02T13:00:00');

	await Promise.all([folder.name([id('1'), id('2')], '412'), folder.name([id('3')], '87')]);
	const written = JSON.parse(await readFile(path.join(directory, 'names.json'), 'utf8'));
	assert.deepEqual(written, {
		version: 1,
		names: { [id('1')]: '412', [id('2')]: '412', [id('3')]: '87' }
	});
	const overview = await folder.overview();
	assert.deepEqual(
		overview.named.map((identity) => [identity.name, identity.ids]),
		[
			['87', [id('3')]],
			['412', [id('2'), id('1')]]
		]
	);
	assert.equal(overview.namedDays, 2);

	// A box on the live picture looks up the sighting it shows.
	assert.deepEqual(await folder.sighting(id('3')), {
		id: id('3'),
		seen: '2026-10-02T13:00:00',
		crops: 1,
		outlines: [outline],
		name: '87'
	});

	await folder.unname([id('2')]);
	assert.deepEqual(
		(await folder.overview()).named.map((identity) => identity.ids),
		[[id('3')], [id('1')]]
	);
	assert.equal((await folder.overview()).unnamed, 1);
});

test('only existing sightings can be named and only their pictures are served', async (t) => {
	const directory = await temporaryDirectory(t, 'individuals-');
	const folder = new IndividualsFolder(directory);
	await sighting(directory, id('1'), '2026-10-01T12:00:00');
	await assert.rejects(folder.name([id('1'), id('9')], '412'), SightingMissingError);
	await assert.rejects(readFile(path.join(directory, 'names.json')), { code: 'ENOENT' });
	assert.equal(await folder.sighting(id('9')), null);
	assert.equal(await folder.sighting('../sightings'), null);

	assert.equal(
		folder.picture(id('1'), 'crop-1.jpg'),
		path.join(directory, 'sightings', id('1'), 'crop-1.jpg')
	);
	for (const [sightingId, picture] of [
		[id('1'), 'sighting.json'],
		[id('1'), '../crop-1.jpg'],
		['..', 'crop-1.jpg'],
		[id('1'), 'crop-0.jpg']
	])
		assert.equal(folder.picture(sightingId, picture), null);
});

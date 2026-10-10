import assert from 'node:assert/strict';
import { mkdtemp, readdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test, type TestContext } from 'node:test';
import { axisTicks, watchedTime } from '../src/lib/camera-history.ts';
import { WatchHistory } from '../src/lib/server/watch-history.ts';

async function directory(t: TestContext): Promise<string> {
	const dir = await mkdtemp(path.join(tmpdir(), 'watch-history-'));
	t.after(() => rm(dir, { recursive: true, force: true }));
	return dir;
}
// Local times, as the files are kept by this computer's calendar days.
const at = (dayOfMonth: number, hour: number, minute = 0, second = 0) =>
	new Date(2026, 9, dayOfMonth, hour, minute, second);
const shape = (stretches: { from: string; to: string; state: string }[] = []) =>
	stretches.map(({ from, to, state }) => [new Date(from).getTime(), new Date(to).getTime(), state]);

test('a state lasts until the next change, and only changes are written', async (t) => {
	const dir = await directory(t);
	const history = new WatchHistory(dir);
	await history.start();
	await history.sample([{ id: 'barn', state: 'connecting' }], at(6, 8));
	await history.sample([{ id: 'barn', state: 'watched' }], at(6, 8, 0, 10));
	await history.sample([{ id: 'barn', state: 'watched' }], at(6, 9));
	await history.sample([{ id: 'barn', state: 'offline' }], at(6, 10));
	await history.sample([{ id: 'barn', state: 'offline' }], at(6, 10, 30));

	const stretches = (await history.read(at(6, 0), at(6, 23))).get('barn');
	assert.deepEqual(shape(stretches), [
		[at(6, 8).getTime(), at(6, 8, 0, 10).getTime(), 'connecting'],
		[at(6, 8, 0, 10).getTime(), at(6, 10).getTime(), 'watched'],
		// The last state lasts until the application was last seen running.
		[at(6, 10).getTime(), at(6, 10, 30).getTime(), 'offline']
	]);
	assert.equal(watchedTime(stretches!), 2 * 3600000 - 10000);
	assert.equal((await readFile(path.join(dir, '2026-10-06.jsonl'), 'utf8')).split('\n').length, 4);
});

test('time the application was not running is not counted as watched', async (t) => {
	const dir = await directory(t);
	const before = new WatchHistory(dir);
	await before.start();
	await before.sample([{ id: 'barn', state: 'watched' }], at(6, 8));
	await before.sample([{ id: 'barn', state: 'watched' }], at(6, 9));

	// The computer was switched off at nine and started again at eleven.
	const after = new WatchHistory(dir);
	await after.start();
	await after.sample([{ id: 'barn', state: 'watched' }], at(6, 11));
	await after.sample([{ id: 'barn', state: 'watched' }], at(6, 12));

	assert.deepEqual(shape((await after.read(at(6, 0), at(6, 23))).get('barn')), [
		[at(6, 8).getTime(), at(6, 9).getTime(), 'watched'],
		[at(6, 9).getTime(), at(6, 11).getTime(), 'stopped'],
		[at(6, 11).getTime(), at(6, 12).getTime(), 'watched']
	]);
});

test('a state continues across midnight and each day can be read by itself', async (t) => {
	const dir = await directory(t);
	const history = new WatchHistory(dir);
	await history.start();
	await history.sample([{ id: 'barn', state: 'watched' }], at(6, 22));
	await history.sample([{ id: 'barn', state: 'watched' }], at(7, 2));

	assert.deepEqual(shape((await history.read(at(6, 20), at(7, 6))).get('barn')), [
		[at(6, 22).getTime(), at(7, 2).getTime(), 'watched']
	]);
	assert.deepEqual(shape((await history.read(at(7, 1), at(7, 6))).get('barn')), [
		[at(7, 1).getTime(), at(7, 2).getTime(), 'watched']
	]);
});

test('a removed camera stops, and files older than thirty days are deleted', async (t) => {
	const dir = await directory(t);
	await writeFile(path.join(dir, '2026-08-01.jsonl'), '');
	const history = new WatchHistory(dir);
	await history.start();
	await history.sample(
		[
			{ id: 'barn', state: 'watched' },
			{ id: 'pen', state: 'watched' }
		],
		at(6, 8)
	);
	await history.sample([{ id: 'barn', state: 'watched' }], at(6, 9));
	await history.sample([{ id: 'barn', state: 'watched' }], at(6, 10));

	const read = await history.read(at(6, 0), at(6, 23));
	assert.deepEqual(shape(read.get('pen')), [
		[at(6, 8).getTime(), at(6, 9).getTime(), 'watched'],
		[at(6, 9).getTime(), at(6, 10).getTime(), 'stopped']
	]);
	assert.deepEqual((await readdir(dir)).sort(), ['2026-10-06.jsonl', 'alive']);
});

test('axis ticks fall on round moments of the day', () => {
	assert.deepEqual(
		axisTicks(at(6, 13, 47).getTime(), at(6, 14, 47).getTime(), 600000),
		[50, 0, 10, 20, 30, 40].map((minute) => at(6, minute === 50 ? 13 : 14, minute).getTime())
	);
	assert.deepEqual(axisTicks(at(6, 21).getTime(), at(7, 21).getTime(), 86400000), [
		at(7, 0).getTime()
	]);
});

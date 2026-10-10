import assert from 'node:assert/strict';
import { test } from 'node:test';
import { serialQueue } from '../src/lib/server/serial.ts';

test('queued operations run one at a time in the order given, and a failure stops only its caller', async () => {
	const enqueue = serialQueue();
	const other = serialQueue();
	const events: string[] = [];
	let release!: () => void;
	const blocked = new Promise<void>((resolve) => (release = resolve));

	const first = enqueue(async () => {
		events.push('first starts');
		await blocked;
		events.push('first ends');
		return 1;
	});
	const failure = new Error('not saved');
	const second = enqueue(async () => {
		events.push('second');
		throw failure;
	});
	const third = enqueue(async () => {
		events.push('third');
		return 3;
	});
	// Another owner's queue does not wait for this one.
	assert.equal(await other(async () => 'independent'), 'independent');
	assert.deepEqual(events, ['first starts']);

	release();
	assert.equal(await first, 1);
	await assert.rejects(second, (error) => error === failure);
	assert.equal(await third, 3);
	assert.deepEqual(events, ['first starts', 'first ends', 'second', 'third']);
});

test('an operation that throws before its first wait is a rejection like any other', async () => {
	const enqueue = serialQueue();
	const failure = new Error('refused');
	await assert.rejects(
		enqueue(() => {
			throw failure;
		}),
		(error) => error === failure
	);
	assert.equal(await enqueue(async () => 'next'), 'next');
});

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { PreviewSlots } from '../src/lib/preview-slots.ts';

test('only four viewers run and releasing a connection resumes the next waiting viewer', () => {
	const slots = new PreviewSlots();
	const starts: number[] = [];
	const release = Array.from({ length: 6 }, (_, index) => slots.request(() => starts.push(index)));
	assert.deepEqual(starts, [0, 1, 2, 3]);
	release[1]();
	assert.deepEqual(starts, [0, 1, 2, 3, 4]);
	release[0]();
	assert.deepEqual(starts, [0, 1, 2, 3, 4, 5]);
});

test('a hidden or closed waiting viewer is removed from the queue', () => {
	const slots = new PreviewSlots(1);
	const starts: string[] = [];
	const releaseFirst = slots.request(() => starts.push('first'));
	const cancelWaiting = slots.request(() => starts.push('cancelled'));
	slots.request(() => starts.push('last'));
	cancelWaiting();
	releaseFirst();
	assert.deepEqual(starts, ['first', 'last']);
});

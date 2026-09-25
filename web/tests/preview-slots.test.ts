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

test('opening a paused preview keeps the connection limit and resumes the displaced preview afterward', () => {
	const slots = new PreviewSlots(2);
	const active = new Set<string>();
	const notify = (name: string) => (running: boolean) => {
		if (running) active.add(name);
		else active.delete(name);
	};
	slots.request(notify('first'));
	slots.request(notify('second'));
	const release = slots.request(notify('requested'), true);
	assert.deepEqual([...active].sort(), ['first', 'requested']);
	release();
	active.delete('requested');
	assert.deepEqual([...active].sort(), ['first', 'second']);
});

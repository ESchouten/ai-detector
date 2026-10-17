import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
	clipLength,
	dataSize,
	dayHeading,
	percent,
	plural,
	recentMoment,
	timeOfDay
} from '../src/lib/format.ts';

test('recent days read as words and older days keep their date', () => {
	const now = new Date(2026, 9, 3, 21, 30);
	assert.equal(dayHeading('2026-10-03', now), 'Today');
	assert.equal(dayHeading('2026-10-02', now), 'Yesterday');
	assert.match(dayHeading('2026-09-28', now), /28/);
	assert.doesNotMatch(dayHeading('2026-09-28', now), /2026/);
	assert.match(dayHeading('2025-12-31', now), /2025/);
	assert.equal(dayHeading('not-a-day', now), 'not-a-day');
	// Yesterday crosses month boundaries.
	assert.equal(dayHeading('2026-09-30', new Date(2026, 9, 1, 0, 5)), 'Yesterday');
});

test('a moment today is its time, and a moment on another day names that day', () => {
	const now = new Date(2026, 9, 12, 6, 31);
	const night = new Date(2026, 9, 12, 2, 10);
	assert.equal(recentMoment(night, now), timeOfDay(night));
	const evening = recentMoment(new Date(2026, 9, 11, 22, 10), now);
	assert.match(evening, /Sun/);
	assert.match(evening, /Oct/);
	assert.match(evening, /11/);
	assert.match(evening, /10:10/);
	assert.doesNotMatch(evening, /2026/);
});

test('clip lengths, sizes and counts are short and unambiguous', () => {
	assert.equal(clipLength(6.4), '0:06');
	assert.equal(clipLength(102), '1:42');
	assert.equal(clipLength(-1), '0:00');
	assert.equal(dataSize(350 * 1024 ** 2), '350 MB');
	assert.equal(dataSize(1.5 * 1024 ** 3), '1.5 GB');
	assert.equal(dataSize(12.34 * 1024 ** 3), '12.3 GB');
	assert.equal(dataSize(137.4 * 1024 ** 3), '137 GB');
	assert.equal(percent(0.624), '62%');
	assert.equal(plural(1, ['# camera', '# cameras']), '1 camera');
	assert.equal(plural(3, ['# camera', '# cameras']), '3 cameras');
	assert.equal(plural(0, ['# camera', '# cameras']), '0 cameras');
	// French counts 0 and 1 as singular and has a separate form for millions.
	const french = ['# caméra', '# de caméras', '# caméras'];
	assert.equal(plural(0, french, 'fr'), '0 caméra');
	assert.equal(plural(2, french, 'fr'), '2 caméras');
	assert.match(plural(1500, ['# recording', '# recordings'], 'en'), /^1,500 recordings$/);
});

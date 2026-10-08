import assert from 'node:assert/strict';
import { test } from 'node:test';
import { clipLength, dayHeading, gigabytes, percent, plural } from '../src/lib/format.ts';
import { recordingVerdict } from '../src/lib/detections.ts';

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

test('clip lengths, sizes and counts are short and unambiguous', () => {
	assert.equal(clipLength(6.4), '0:06');
	assert.equal(clipLength(102), '1:42');
	assert.equal(clipLength(-1), '0:00');
	assert.equal(gigabytes(1.5 * 1024 ** 3), '1.5 GB');
	assert.equal(gigabytes(137.4 * 1024 ** 3), '137 GB');
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

test('a recording shows who decided its outcome, and a failed AI check is not a verdict', () => {
	const review = {
		validated: true,
		source: 'telegram' as const,
		reviewed_at: '2026-10-03T10:00:00Z'
	};
	assert.equal(
		recordingVerdict({ stage: 'unvalidated', review: null, validation_error: null }),
		null
	);
	assert.deepEqual(recordingVerdict({ stage: 'approved', review: null, validation_error: null }), {
		tone: 'ok',
		label: 'Confirmed',
		source: 'Checked by AI'
	});
	assert.deepEqual(recordingVerdict({ stage: 'approved', review, validation_error: null }), {
		tone: 'ok',
		label: 'Confirmed',
		source: 'Reviewed in Telegram'
	});
	assert.deepEqual(
		recordingVerdict({
			stage: 'rejected',
			review: { ...review, validated: false, source: 'web' },
			validation_error: 'Timed out'
		}),
		{ tone: 'neutral', label: 'False alarm', source: 'Reviewed by you' }
	);
	assert.deepEqual(
		recordingVerdict({ stage: 'unvalidated', review: null, validation_error: 'Timed out' }),
		{ tone: 'warn', label: 'AI check failed', source: 'Not checked', detail: 'Timed out' }
	);
});

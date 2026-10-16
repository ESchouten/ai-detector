import assert from 'node:assert/strict';
import { test } from 'node:test';
import { recordingPresets, recordingVerdict } from '../src/lib/detections.ts';
import type { Configuration } from '../src/lib/schema.ts';

test('recordings use their preset color without guessing when different presets share a folder', () => {
	const document: Configuration = {
		config: {
			detectors: [
				{
					detection: { source: ['camera-1'] },
					exporters: { disk: [{ directory: 'visitors' }, { directory: 'shared' }] }
				},
				{
					detection: { source: ['camera-2'] },
					exporters: { disk: [{ directory: 'deliveries' }, { directory: 'shared' }, {}] }
				}
			]
		},
		app: {
			streams: [],
			telegrams: [],
			llms: [],
			detectors: [
				{ label: 'Entrance', preset: 'people' },
				{ label: 'Loading bay', preset: 'vehicles' }
			]
		}
	};
	assert.deepEqual(recordingPresets(document), {
		visitors: 'people',
		deliveries: 'vehicles',
		shared: 'shared'
	});
	document.app.detectors[0].label = 'Renamed entrance';
	assert.equal(recordingPresets(document).visitors, 'people');
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
		source: 'Checked by AI'
	});
	assert.deepEqual(recordingVerdict({ stage: 'approved', review, validation_error: null }), {
		source: 'Reviewed in Telegram'
	});
	assert.deepEqual(
		recordingVerdict({
			stage: 'rejected',
			review: { ...review, validated: false, source: 'web' },
			validation_error: 'Timed out'
		}),
		{ source: 'Reviewed by you' }
	);
	assert.deepEqual(
		recordingVerdict({ stage: 'unvalidated', review: null, validation_error: 'Timed out' }),
		{ source: 'Not checked', failure: 'Timed out' }
	);
});

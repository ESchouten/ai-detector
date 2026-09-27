import assert from 'node:assert/strict';
import { test } from 'node:test';
import { recordingPresets } from '../src/lib/detections.ts';
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

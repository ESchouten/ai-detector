import assert from 'node:assert/strict';
import { test } from 'node:test';
import { cameraStatusBadge } from '../src/lib/camera-status.ts';
import { badgeHue } from '../src/lib/badge-colors.ts';
import type { CameraRuntimeStatus } from '../src/lib/runtime.ts';

const runtime = { managed: true, readiness: 'monitoring' as const };
const camera: CameraRuntimeStatus = {
	id: 'camera-1',
	label: 'Camera 1',
	sourceKey: 'source-1',
	state: 'monitoring',
	lastFrameAt: null,
	lastProcessedAt: null,
	lastInferenceAt: null,
	lastRecordingAt: null
};

test('camera badges distinguish connection, processing and recording problems', () => {
	assert.equal(cameraStatusBadge(camera, runtime, false).tone, 'ok');
	assert.equal(
		cameraStatusBadge({ ...camera, state: 'offline' }, runtime, false).label,
		'Camera offline'
	);
	assert.equal(
		cameraStatusBadge({ ...camera, error: 'Processing is stale' }, runtime, false).label,
		'Detection delayed'
	);
	assert.equal(
		cameraStatusBadge({ ...camera, recordingError: 'Disk full' }, runtime, false).label,
		'Recording failed'
	);
	assert.equal(
		cameraStatusBadge(undefined, { ...runtime, readiness: 'failed' }, false).label,
		'Detection stopped'
	);
});

test('paused and unknown status never claim monitoring or an old camera failure', () => {
	const failed = { ...camera, error: 'Old error', recordingError: 'Old recording error' };
	assert.deepEqual(cameraStatusBadge(failed, { ...runtime, readiness: 'idle' }, false), {
		label: 'Paused',
		tone: 'neutral'
	});
	assert.equal(cameraStatusBadge(camera, runtime, true).label, 'Status unavailable');
	assert.equal(
		cameraStatusBadge(camera, { ...runtime, managed: false }, false).label,
		'Status unavailable'
	);
	assert.equal(
		cameraStatusBadge(undefined, { ...runtime, readiness: 'preparing' }, false).label,
		'Preparing'
	);
});

test('preset IDs and display names keep their color and the bundled presets differ', () => {
	assert.equal(badgeHue('cow-catcher'), badgeHue('Cow Catcher'));
	assert.equal(badgeHue('calving-catcher'), badgeHue('Calving Catcher'));
	assert.notEqual(badgeHue('cow-catcher'), badgeHue('calving-catcher'));
});

import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { test } from 'node:test';
import { RuntimeProgress, STATUS_PREFIX } from '../src/lib/server/runtime-status.ts';

const source = 'rtsp://farmer:secret@camera.example.test/live';
const sourceKey = createHash('sha256').update(source).digest('hex');
const now = Date.parse('2026-09-22T12:00:00Z');

function progress() {
	const state = new RuntimeProgress();
	state.configure(
		{
			detectors: [
				{
					detection: { source: [source] },
					yolo: { model: 'model.onnx' },
					exporters: { disk: [{}] }
				}
			]
		},
		{ streams: [{ id: 'stable-camera', label: 'Barn', source }], telegrams: [], detectors: [] },
		'/data'
	);
	return state;
}

function record(
	state: RuntimeProgress,
	event: string,
	message?: string,
	at = now,
	identity: { ruleId?: string; destinationId?: string } = {}
) {
	state.accept(
		STATUS_PREFIX +
			JSON.stringify({
				version: 1,
				event,
				sourceKey,
				at: new Date(at).toISOString(),
				message,
				ruleId: 'detector-1',
				destinationId: 'disk-1',
				...identity
			})
	);
}

test('camera readiness requires actual frames and processing; recordings remain separately observed', () => {
	const state = progress();
	assert.equal(state.snapshot(now).readiness, 'preparing');
	record(state, 'ready');
	assert.equal(state.snapshot(now).readiness, 'connecting');
	record(state, 'frame');
	assert.equal(state.snapshot(now).cameras[0].state, 'receiving');
	record(state, 'inference');
	const ready = state.snapshot(now);
	assert.equal(ready.readiness, 'monitoring');
	assert.equal(ready.cameras[0].id, 'stable-camera');
	assert.equal(ready.cameras[0].label, 'Barn');
	assert.equal(ready.cameras[0].lastRecordingAt, null);
	assert.ok(!JSON.stringify(ready).includes('secret'));
	record(state, 'recording_failed', 'Disk is full');
	assert.equal(state.snapshot(now).readiness, 'degraded');
	assert.equal(state.snapshot(now).cameras[0].state, 'monitoring');
	assert.match(state.snapshot(now).cameras[0].recordingError!, /Disk is full/);
	record(state, 'recording');
	assert.equal(state.snapshot(now).readiness, 'monitoring');
	assert.equal(state.snapshot(now).cameras[0].recordingError, undefined);
});

test('preparation failures remain actionable until a new run resets progress', () => {
	const state = progress();
	record(state, 'preparing', 'Downloading the detection model…');
	assert.match(state.preparation!, /Rule 1: Downloading/);
	record(state, 'preparation_failed', 'Check the internet connection and try again.');
	assert.equal(state.snapshot(now).readiness, 'failed');
	assert.match(state.preparationFailure!, /internet connection/);
	state.configure({ detectors: [] }, { streams: [], telegrams: [], detectors: [] }, '/data');
	assert.equal(state.preparationFailure, undefined);
	assert.equal(state.preparation, undefined);
});

test('offline cameras need a new frame; completion of an old batch does not claim recovery', () => {
	const state = progress();
	record(state, 'frame');
	record(state, 'inference');
	record(state, 'offline', 'Camera disconnected');
	record(state, 'inference');
	assert.equal(state.snapshot(now).cameras[0].state, 'offline');
	record(state, 'frame');
	assert.equal(state.snapshot(now).cameras[0].state, 'receiving');
	record(state, 'inference');
	assert.equal(state.snapshot(now).readiness, 'monitoring');
	assert.equal(state.snapshot(now + 16000).readiness, 'degraded');
	assert.equal(state.snapshot(now + 16000).cameras[0].state, 'offline');
});

test('processing that has stopped completing is visible even while fresh camera frames arrive', () => {
	const state = progress();
	record(state, 'frame');
	record(state, 'inference');
	record(state, 'frame', undefined, now + 16000);
	const stale = state.snapshot(now + 16000);
	assert.equal(stale.readiness, 'degraded');
	assert.equal(stale.cameras[0].state, 'receiving');
	assert.match(stale.cameras[0].error!, /processing has not completed/);
});

test('unsupported, invalid and unknown-camera status records cannot create monitoring success', () => {
	const state = progress();
	for (const value of [
		'{broken',
		JSON.stringify({ version: 2, event: 'inference', at: new Date(now).toISOString(), sourceKey }),
		JSON.stringify({ version: 1, event: 'inference', at: 'tomorrow', sourceKey }),
		JSON.stringify({
			version: 1,
			event: 'inference',
			at: new Date(now).toISOString(),
			sourceKey: 'f'.repeat(64)
		})
	])
		state.accept(STATUS_PREFIX + value);
	assert.equal(state.snapshot(now).readiness, 'preparing');
	assert.equal(state.snapshot(now).cameras[0].lastInferenceAt, null);
});

test('snapshot processing does not fabricate inference activity, and restart clears old evidence', () => {
	const state = progress();
	record(state, 'frame');
	record(state, 'processed');
	assert.equal(state.snapshot(now).readiness, 'monitoring');
	assert.equal(state.snapshot(now).cameras[0].lastInferenceAt, null);
	state.configure(
		{ detectors: [{ detection: { source: [source] } }] },
		{ streams: [], telegrams: [], detectors: [] },
		'/data'
	);
	assert.equal(state.snapshot(now).readiness, 'preparing');
	assert.equal(state.snapshot(now).cameras[0].lastProcessedAt, null);
});

test('every rule must process the camera, and a healthy rule cannot hide another stalled rule', () => {
	const state = new RuntimeProgress();
	state.configure(
		{
			detectors: [
				{ detection: { source: [source] }, yolo: { model: 'first.onnx' } },
				{ detection: { source: [source] }, yolo: { model: 'second.onnx' } }
			]
		},
		{ streams: [], telegrams: [], detectors: [{ label: 'Calving' }, { label: 'Mounts' }] },
		'/data'
	);
	record(state, 'frame');
	record(state, 'inference');
	assert.equal(state.snapshot(now).cameras[0].state, 'receiving');
	record(state, 'inference', undefined, now, { ruleId: 'detector-2' });
	assert.equal(state.snapshot(now).readiness, 'monitoring');
	record(state, 'frame', undefined, now + 16000);
	record(state, 'inference', undefined, now + 16000);
	assert.equal(state.snapshot(now + 16000).readiness, 'degraded');
	assert.match(state.snapshot(now + 16000).cameras[0].error!, /Mounts/);
});

test('recording failures remain attached to their rule and destination until that destination succeeds', () => {
	const state = new RuntimeProgress();
	state.configure(
		{
			detectors: [
				{ detection: { source: [source] }, exporters: { disk: [{}, {}] } },
				{ detection: { source: [source] }, exporters: { disk: [{}] } }
			]
		},
		{ streams: [], telegrams: [], detectors: [{ label: 'Calving' }, { label: 'Mounts' }] },
		'/data'
	);
	record(state, 'frame');
	record(state, 'processed');
	record(state, 'processed', undefined, now, { ruleId: 'detector-2' });
	record(state, 'recording_failed', 'Disk is full');
	record(state, 'recording', undefined, now, { ruleId: 'detector-2' });
	record(state, 'recording', undefined, now, { destinationId: 'disk-2' });
	assert.equal(state.snapshot(now).readiness, 'degraded');
	assert.match(state.snapshot(now).cameras[0].recordingError!, /Calving: Disk is full/);
	record(state, 'recording');
	assert.equal(state.snapshot(now).readiness, 'monitoring');
});

import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { test } from 'node:test';
import { RuntimeProgress, STATUS_PREFIX } from '../src/lib/server/runtime-status.ts';
import { sourceKey as keyOf } from '../src/lib/server/source-key.ts';

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
		{
			streams: [{ id: 'stable-camera', label: 'Barn', source }],
			telegrams: [],
			llms: [],
			detectors: []
		},
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

test('status names each camera by the key the detector reports for its source', () => {
	const state = new RuntimeProgress();
	const sources = ['clips/yard.mp4', '0', source];
	state.configure(
		{ detectors: [{ detection: { source: sources } }] },
		{ streams: [], telegrams: [], llms: [], detectors: [] },
		'/data'
	);
	const hash = (value: string) => createHash('sha256').update(value).digest('hex');
	const keys = state.snapshot(now).cameras.map((camera) => camera.sourceKey);
	// The detector hashes the source it opens: a local file by its full path.
	assert.deepEqual(keys, [hash(path.resolve('/data', 'clips/yard.mp4')), hash('0'), hash(source)]);
	assert.deepEqual(
		keys,
		sources.map((item) => keyOf(item, '/data'))
	);
});

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
	record(
		state,
		'delivery_failed',
		'Delivery failed. Check the connection and see Logs for details.'
	);
	assert.equal(state.snapshot(now).readiness, 'degraded');
	assert.equal(state.snapshot(now).cameras[0].state, 'monitoring');
	assert.match(state.snapshot(now).cameras[0].recordingError!, /Check free disk space/);
	assert.deepEqual(state.issues, []);
	record(state, 'delivery');
	assert.equal(state.snapshot(now).readiness, 'monitoring');
	assert.equal(state.snapshot(now).cameras[0].recordingError, undefined);
	assert.equal(Date.parse(state.snapshot(now).cameras[0].lastRecordingAt!), now);
});

test('preparation failures remain actionable until a new run resets progress', () => {
	const state = progress();
	record(state, 'preparing', 'Downloading the detection model…');
	assert.match(state.preparation!, /Detector 1: Downloading/);
	record(state, 'preparation_failed', 'Check the internet connection and try again.');
	assert.equal(state.snapshot(now).readiness, 'failed');
	assert.match(state.preparationFailure!, /internet connection/);
	state.configure(
		{ detectors: [] },
		{ streams: [], telegrams: [], llms: [], detectors: [] },
		'/data'
	);
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

test('stall recovery waits for readiness and fresh frames, and does not restart an offline camera', () => {
	const state = progress();
	record(state, 'frame');
	record(state, 'frame', undefined, now + 121000);
	assert.equal(state.stalledDetector(now + 121000), undefined, 'Model preparation may be slow');
	record(state, 'ready');
	assert.equal(state.stalledDetector(now + 121000), 'Detector 1');
	record(state, 'inference', undefined, now + 121000);
	assert.equal(state.stalledDetector(now + 121000), undefined);
	assert.equal(
		state.stalledDetector(now + 300000),
		undefined,
		'No recent frames means camera recovery'
	);
	record(state, 'frame', undefined, now + 300000);
	record(state, 'offline');
	assert.equal(state.stalledDetector(now + 300000), undefined);
});

test('validator and delivery failures remain visible until that connection succeeds', () => {
	const state = progress();
	record(state, 'frame');
	record(state, 'inference');
	record(state, 'backend', 'ENGINE on cuda:0');
	record(state, 'validation_failed', 'Validator unavailable');
	record(state, 'delivery_failed', 'Delivery unavailable', now, { destinationId: 'telegram-1' });
	assert.equal(state.snapshot(now).readiness, 'degraded');
	assert.equal(state.issues.length, 2);
	assert.deepEqual(state.backends, [{ label: 'Detector 1', engine: 'ENGINE on cuda:0' }]);
	record(state, 'validation');
	assert.deepEqual(state.issues, ['Detector 1 · Telegram alert: Delivery unavailable']);
	record(state, 'delivery', undefined, now, { destinationId: 'telegram-1' });
	assert.equal(state.snapshot(now).readiness, 'monitoring');
});

test('delivery backpressure keeps the worker alive without pretending inference completed', () => {
	const state = progress();
	record(state, 'ready');
	record(state, 'frame');
	record(state, 'inference');
	record(state, 'waiting_delivery', undefined, now + 180000);
	record(state, 'frame', undefined, now + 180000);
	assert.equal(state.stalledDetector(now + 180000), undefined);
	const status = state.snapshot(now + 180000).cameras[0];
	assert.match(status.error!, /waiting for AI validation or delivery/);
	assert.equal(Date.parse(status.lastProcessedAt!), now);
	record(state, 'processing_resumed', undefined, now + 181000);
	assert.equal(state.stalledDetector(now + 182000), undefined);
	assert.match(state.snapshot(now + 182000).cameras[0].error!, /processing has not completed/);
	record(state, 'frame', undefined, now + 303000);
	assert.equal(state.stalledDetector(now + 303000), 'Detector 1');
});

test('a lost queue-wait signal cannot suppress stall recovery indefinitely', () => {
	const state = progress();
	record(state, 'ready');
	record(state, 'frame');
	record(state, 'waiting_delivery');
	record(state, 'waiting_delivery', undefined, now + 180000, { ruleId: 'detector-99' });
	record(state, 'frame', undefined, now + 180000);
	assert.equal(state.stalledDetector(now + 180000), 'Detector 1');
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
		{ streams: [], telegrams: [], llms: [], detectors: [] },
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
		{
			streams: [],
			telegrams: [],
			llms: [],
			detectors: [{ label: 'Calving' }, { label: 'Mounts' }]
		},
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
		{
			streams: [],
			telegrams: [],
			llms: [],
			detectors: [{ label: 'Calving' }, { label: 'Mounts' }]
		},
		'/data'
	);
	record(state, 'frame');
	record(state, 'processed');
	record(state, 'processed', undefined, now, { ruleId: 'detector-2' });
	record(state, 'delivery_failed');
	record(state, 'delivery', undefined, now, { ruleId: 'detector-2' });
	record(state, 'delivery', undefined, now, { destinationId: 'disk-2' });
	assert.equal(state.snapshot(now).readiness, 'degraded');
	assert.match(
		state.snapshot(now).cameras[0].recordingError!,
		/^Calving: A recording could not be saved/
	);
	record(state, 'delivery');
	assert.equal(state.snapshot(now).readiness, 'monitoring');
});

import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { test } from 'node:test';
import { RuntimeProgress, STATUS_PREFIX } from '../src/lib/server/runtime-status.ts';
import type { Config } from '../src/lib/schema.ts';

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
	identity: { ruleId?: string; destinationId?: string; sourceEpoch?: string } = {}
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
	assert.equal(state.issues.length, 1);
	record(state, 'delivery', undefined, now, { destinationId: 'telegram-1' });
	assert.equal(state.snapshot(now).readiness, 'monitoring');
});

test('identity preparation and recovery are per rule and do not erase other failures or notices', () => {
	const state = new RuntimeProgress();
	const config: Config = {
		detectors: [
			{ detection: { source: [source] }, identity: { labels: ['cow'] } },
			{ detection: { source: [source] }, identity: { labels: ['cow'] } }
		]
	};
	const app = {
		streams: [],
		telegrams: [],
		llms: [],
		detectors: [{ label: 'Barn identity' }, { label: 'Passage identity' }]
	};
	state.configure(config, app, '/data');
	record(state, 'notice', 'Other runtime information');
	record(state, 'identity_collecting', 'Name two cows first.');
	assert.equal(state.identification[0].state, 'collecting');
	assert.equal(
		state.snapshot(now).readiness,
		'preparing',
		'Identity status is not camera readiness'
	);
	record(state, 'frame');
	record(state, 'inference');
	record(state, 'inference', undefined, now, { ruleId: 'detector-2' });
	record(state, 'identity_preparing', 'Preparing references.');
	record(state, 'identity_failed', 'Reference photo missing.', now, { ruleId: 'detector-2' });
	record(state, 'identity_ready', 'Suggestions ready.');
	assert.deepEqual(state.identification, [
		{ ruleId: 'detector-1', label: 'Barn identity', state: 'ready', message: 'Suggestions ready.' },
		{
			ruleId: 'detector-2',
			label: 'Passage identity',
			state: 'failed',
			message: 'Reference photo missing.'
		}
	]);
	assert.equal(state.notice, 'Other runtime information');
	assert.equal(state.snapshot(now).readiness, 'degraded');
	assert.equal(state.snapshot(now).cameras[0].state, 'monitoring', 'Detection continues');
	record(state, 'identity_ready', undefined, now, { ruleId: 'detector-2' });
	assert.equal(state.snapshot(now).readiness, 'monitoring');
	state.configure(config, app, '/data');
	assert.deepEqual(state.identification, [], 'A fresh run cannot inherit earlier readiness');
});

test('identity events without a configured rule cannot create success or a phantom failure', () => {
	const state = progress();
	record(state, 'identity_failed', 'Unknown rule', now, { ruleId: 'detector-99' });
	record(state, 'identity_ready', undefined, now, { ruleId: undefined });
	assert.deepEqual(state.identification, []);
	assert.equal(state.snapshot(now).readiness, 'preparing');
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
	record(state, 'recording_failed', 'Disk is full');
	record(state, 'recording', undefined, now, { ruleId: 'detector-2' });
	record(state, 'recording', undefined, now, { destinationId: 'disk-2' });
	assert.equal(state.snapshot(now).readiness, 'degraded');
	assert.match(state.snapshot(now).cameras[0].recordingError!, /Calving: Disk is full/);
	record(state, 'recording');
	assert.equal(state.snapshot(now).readiness, 'monitoring');
});

test('an unthrottled capture epoch clears previous inference readiness on reconnect or geometry change', () => {
	const state = progress();
	record(state, 'frame');
	record(state, 'inference');
	assert.equal(state.snapshot(now).cameras[0].state, 'monitoring');
	const epoch = (at: number, sourceEpoch: string) =>
		state.accept(
			STATUS_PREFIX +
				JSON.stringify({
					version: 1,
					event: 'source_epoch',
					sourceKey,
					sourceEpoch,
					at: new Date(at).toISOString()
				})
		);
	assert.equal(epoch(now + 10, 'resized')?.sourceEpoch, 'resized');
	assert.equal(state.snapshot(now + 10).cameras[0].state, 'receiving');
	record(state, 'inference', undefined, now + 20);
	record(state, 'offline', 'Disconnected', now + 30);
	epoch(now + 40, 'reconnected');
	assert.equal(state.snapshot(now + 40).cameras[0].state, 'receiving');
	assert.equal(state.snapshot(now + 40).cameras[0].error, undefined);
});

for (const kind of ['inference', 'processed']) {
	test(`late ${kind} cannot mark a reconnected camera as monitored or hide its stall`, () => {
		const state = progress();
		record(state, 'frame');
		record(state, kind); // Legacy runs still become ready without capture metadata.
		assert.equal(state.snapshot(now).cameras[0].state, 'monitoring');
		record(state, 'offline', 'Disconnected', now + 1);
		record(state, 'source_epoch', undefined, now + 2, { sourceEpoch: 'new' });
		record(state, kind, undefined, now + 3, { sourceEpoch: 'old' });
		record(state, kind, undefined, now + 4); // Missing metadata is stale once epoch is declared.
		const pending = state.snapshot(now + 4).cameras[0];
		assert.equal(pending.state, 'receiving');
		assert.equal(pending.lastProcessedAt, new Date(now).toISOString());
		record(state, kind, undefined, now + 5, { sourceEpoch: 'new' });
		assert.equal(state.snapshot(now + 5).cameras[0].state, 'monitoring');
		record(state, kind, undefined, now + 6, { sourceEpoch: 'old' });
		assert.equal(
			state.snapshot(now + 6).cameras[0].lastProcessedAt,
			new Date(now + 5).toISOString()
		);
		assert.equal(
			state.accept(
				STATUS_PREFIX +
					JSON.stringify({
						version: 1,
						event: 'source_epoch',
						sourceKey,
						at: new Date(now + 7).toISOString()
					})
			),
			undefined
		); // A malformed epoch cannot erase the continuity guard.
		record(state, kind, undefined, now + 8);
		assert.equal(
			state.snapshot(now + 8).cameras[0].lastProcessedAt,
			new Date(now + 5).toISOString()
		);
	});
}

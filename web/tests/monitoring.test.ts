import assert from 'node:assert/strict';
import { test } from 'node:test';
import { monitoringSummary } from '../src/lib/monitoring.ts';
import type { CameraRuntimeStatus, RuntimeStatus } from '../src/lib/runtime.ts';

const camera: CameraRuntimeStatus = {
	id: 'camera-1',
	label: 'Barn',
	sourceKey: 'source-1',
	state: 'monitoring',
	lastFrameAt: null,
	lastProcessedAt: null,
	lastInferenceAt: null,
	lastRecordingAt: null
};
const runtime: RuntimeStatus = {
	managed: true,
	phase: 'running',
	message: 'Monitoring 2 cameras.',
	dataDirectory: '/data',
	readiness: 'monitoring',
	cameras: [camera, { ...camera, id: 'camera-2', label: 'Yard' }]
};
const scope = { stale: false, configured: true };

test('healthy monitoring is quiet and counts only cameras that are analysed and recorded', () => {
	const summary = monitoringSummary(runtime, scope);
	assert.deepEqual(
		{ tone: summary.tone, attention: summary.attention, action: summary.action },
		{ tone: 'ok', attention: false, action: 'pause' }
	);
	assert.equal(summary.detail, 'Watching 2 cameras.');
	const one = monitoringSummary(
		{ ...runtime, cameras: [camera, { ...camera, recordingError: 'Disk full' }] },
		scope
	);
	assert.equal(one.detail, 'Watching 1 camera.');
});

test('every state in which cameras are not protected asks for attention with its next step', () => {
	const paused = monitoringSummary({ ...runtime, phase: 'stopped', readiness: 'idle' }, scope);
	assert.deepEqual([paused.label, paused.attention, paused.action], ['Paused', true, 'start']);
	const failed = monitoringSummary(
		{ ...runtime, phase: 'failed', readiness: 'failed', message: 'The model could not load.' },
		scope
	);
	assert.deepEqual(
		[failed.tone, failed.attention, failed.action, failed.detail],
		['bad', true, 'retry', 'The model could not load.']
	);
	const offline = monitoringSummary(
		{
			...runtime,
			readiness: 'degraded',
			cameras: [camera, { ...camera, state: 'offline', error: 'No recent camera frames.' }]
		},
		scope
	);
	assert.deepEqual(
		[offline.label, offline.attention, offline.detail],
		['Needs attention', true, '1 camera offline.']
	);
	const delivery = monitoringSummary(
		{ ...runtime, readiness: 'degraded', issues: ['Cow Catcher · telegram-1: Chat not found.'] },
		scope
	);
	assert.equal(delivery.detail, 'Cow Catcher · telegram-1: Chat not found.');
	const recording = monitoringSummary(
		{
			...runtime,
			readiness: 'degraded',
			cameras: [{ ...camera, recordingError: 'Disk full' }]
		},
		scope
	);
	assert.equal(recording.detail, 'Barn: Disk full');
});

test('starting and stopping are in progress, not problems', () => {
	const checking = monitoringSummary(
		{ ...runtime, phase: 'checking', readiness: 'preparing', preparation: 'Optimizing model…' },
		scope
	);
	assert.deepEqual(
		[checking.tone, checking.attention, checking.action, checking.detail],
		['busy', false, 'cancel', 'Optimizing model…']
	);
	assert.equal(monitoringSummary({ ...runtime, phase: 'starting' }, scope).action, null);
	assert.equal(
		monitoringSummary({ ...runtime, readiness: 'connecting' }, scope).label,
		'Connecting cameras…'
	);
	assert.equal(monitoringSummary({ ...runtime, phase: 'stopping' }, scope).tone, 'busy');
});

test('a lost connection outranks the last known state; missing detectors and external detectors are not alarms', () => {
	const stale = monitoringSummary(runtime, { stale: true, configured: true });
	assert.deepEqual([stale.label, stale.attention, stale.action], ['Connection lost', true, null]);
	const viewing = monitoringSummary(
		{ ...runtime, phase: 'stopped', readiness: 'idle', cameras: [] },
		{ stale: false, configured: false }
	);
	assert.deepEqual([viewing.label, viewing.attention], ['Live view only', false]);
	const external = monitoringSummary(
		{ ...runtime, managed: false, phase: 'stopped', readiness: 'idle', cameras: [] },
		scope
	);
	assert.deepEqual(
		[external.label, external.attention, external.action],
		['Runs separately', false, null]
	);
});

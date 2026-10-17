import assert from 'node:assert/strict';
import { test } from 'node:test';
import { badgeHue } from '../src/lib/badge-colors.ts';
import { cameraStatusBadge, monitoringSummary } from '../src/lib/monitoring.ts';
import type { CameraRuntimeStatus, RuntimeStatus } from '../src/lib/runtime.ts';

const camera: CameraRuntimeStatus = {
	id: 'camera-1',
	label: 'Barn',
	sourceKey: 'source-1',
	state: 'monitoring',
	lastFrameAt: null
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

test('a detector that keeps stopping is a problem in every step of its next attempt', () => {
	const failing = 'The detector keeps stopping unexpectedly (1). Restart this computer.';
	for (const phase of ['starting', 'checking', 'running'] as const) {
		const summary = monitoringSummary(
			{
				...runtime,
				phase,
				failing,
				readiness: 'preparing',
				cameras: [],
				message: 'Checking this computer…'
			},
			scope
		);
		assert.deepEqual(
			[summary.tone, summary.label, summary.detail, summary.attention, summary.action],
			['bad', 'Monitoring stopped', failing, true, 'pause'],
			phase
		);
	}
	// On its way down it is stopping, whatever came before.
	assert.equal(
		monitoringSummary({ ...runtime, phase: 'stopping', failing }, scope).label,
		'Stopping…'
	);
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
	// Between the attempts of a detector that keeps stopping, the cameras are not listed at all.
	assert.deepEqual(
		cameraStatusBadge(
			undefined,
			{ ...runtime, readiness: 'preparing', failing: 'The detector keeps stopping.' },
			false
		),
		{ label: 'Detection stopped', tone: 'bad' }
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

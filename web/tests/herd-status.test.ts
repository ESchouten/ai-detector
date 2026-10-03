import assert from 'node:assert/strict';
import { test } from 'node:test';
import { herdEmptyState } from '../src/lib/herd-status.ts';
import type { RuntimeStatus } from '../src/lib/runtime.ts';

const running = { managed: true, phase: 'running', readiness: 'monitoring' } as const;

test('an unrelated running detector does not suggest that cow identity is configured', () => {
	assert.match(herdEmptyState(false, running, false).description, /Add a Cow Identity detector/);
});

test('a saved identity detector guides farmers through pause, preparation and collection', () => {
	const states: [Partial<RuntimeStatus>, RegExp][] = [
		[{ phase: 'stopped', readiness: 'idle' }, /Start monitoring above/],
		[{ phase: 'starting', readiness: 'preparing' }, /Monitoring is starting/],
		[{ readiness: 'connecting' }, /camera connection progress/],
		[{ phase: 'stopping' }, /Start monitoring again/],
		[{ phase: 'failed', readiness: 'failed' }, /monitoring details above/],
		[{ readiness: 'degraded' }, /monitoring details above/],
		[{}, /Small, overlapping or partly hidden cows are skipped/]
	];
	for (const [state, description] of states) {
		const result = herdEmptyState(true, { ...running, ...state }, false);
		assert.match(result.description, description);
		assert.doesNotMatch(result.description, /Add a Cow Identity detector/);
	}
});

test('stale or unmanaged monitoring never claims that the camera is collecting photos', () => {
	for (const [managed, stale] of [
		[false, false],
		[true, true]
	]) {
		const result = herdEmptyState(true, { ...running, managed }, stale);
		assert.equal(result.title, 'Waiting for monitoring status');
		assert.match(result.description, /Open AI Detector on the monitoring computer/);
	}
});

test('working cameras do not imply that identity suggestions are available', () => {
	const identity = { ruleId: 'detector-1', label: 'Cow Identity' };
	assert.equal(
		herdEmptyState(
			true,
			{ ...running, identification: [{ ...identity, state: 'collecting' }] },
			false
		).title,
		'Collecting your first cow photos'
	);
	assert.equal(
		herdEmptyState(
			true,
			{ ...running, identification: [{ ...identity, state: 'preparing' }] },
			false
		).title,
		'Preparing cow identification'
	);
	const failed = {
		...running,
		readiness: 'degraded' as const,
		identification: [
			{ ...identity, state: 'ready' as const },
			{ ...identity, ruleId: 'detector-2', state: 'failed' as const }
		]
	};
	assert.match(herdEmptyState(true, failed, false).description, /cannot currently suggest names/);
	assert.match(
		herdEmptyState(true, { ...failed, phase: 'stopped' }, false).description,
		/Start monitoring above/
	);
	assert.doesNotMatch(
		herdEmptyState(true, { ...failed, phase: 'failed' }, false).description,
		/detection can continue/
	);
	assert.equal(herdEmptyState(true, failed, true).title, 'Waiting for monitoring status');
});

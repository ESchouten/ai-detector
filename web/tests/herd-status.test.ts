import assert from 'node:assert/strict';
import { test } from 'node:test';
import { herdEmptyState } from '../src/lib/herd-status.ts';
import type { RuntimeStatus } from '../src/lib/runtime.ts';

const running = { managed: true, phase: 'running', readiness: 'monitoring' } as const;

test('automatic tracking requires no manual enrollment but does not claim ear-number recognition', () => {
	const automatic = ['continuous'] as const;
	const result = herdEmptyState(automatic, running, false);
	assert.match(result.description, /do not need to name photos/);
	assert.match(result.description, /ear-number recognition is still being developed/);
	assert.equal(result.title, 'Waiting for a clear camera view');
	assert.equal(herdEmptyState(automatic, running, true).title, 'Waiting for monitoring status');
	assert.equal(
		herdEmptyState(automatic, { ...running, phase: 'failed' }, false).title,
		'Monitoring needs attention'
	);
	assert.equal(
		herdEmptyState(
			automatic,
			{
				...running,
				identification: [{ ruleId: 'detector-1', label: 'Cow Identity', state: 'ready' }]
			},
			false
		).title,
		'Following cows automatically'
	);
});

test('an unrelated running detector does not suggest that cow identity is configured', () => {
	assert.match(herdEmptyState([], running, false).description, /Add a Cow Identity detector/);
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
		const result = herdEmptyState(['appearance'], { ...running, ...state }, false);
		assert.match(result.description, description);
		assert.doesNotMatch(result.description, /Add a Cow Identity detector/);
	}
});

test('stale or unmanaged monitoring never claims that the camera is collecting photos', () => {
	for (const [managed, stale] of [
		[false, false],
		[true, true]
	]) {
		const result = herdEmptyState(['appearance'], { ...running, managed }, stale);
		assert.equal(result.title, 'Waiting for monitoring status');
		assert.match(result.description, /Open AI Detector on the monitoring computer/);
	}
});

test('working cameras do not imply that identity suggestions are available', () => {
	const identity = { ruleId: 'detector-1', label: 'Cow Identity' };
	assert.equal(
		herdEmptyState(
			['appearance'],
			{ ...running, identification: [{ ...identity, state: 'collecting' }] },
			false
		).title,
		'Collecting your first cow photos'
	);
	assert.equal(
		herdEmptyState(
			['appearance'],
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
	assert.match(
		herdEmptyState(['appearance'], failed, false).description,
		/cannot currently suggest names/
	);
	assert.match(
		herdEmptyState(['appearance'], { ...failed, phase: 'stopped' }, false).description,
		/Start monitoring above/
	);
	assert.doesNotMatch(
		herdEmptyState(['appearance'], { ...failed, phase: 'failed' }, false).description,
		/detection can continue/
	);
	assert.equal(herdEmptyState(['appearance'], failed, true).title, 'Waiting for monitoring status');
});

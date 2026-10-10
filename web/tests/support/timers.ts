import assert from 'node:assert/strict';
import { syncBuiltinESMExports } from 'node:module';
import { setTimeout } from 'node:timers/promises';
import type { TestContext } from 'node:test';

// Poll real subprocess I/O while application timers advance only when the test asks.
export const realDelay = setTimeout;

export async function waitFor(predicate: () => boolean | Promise<boolean>) {
	for (let i = 0; i < 200; i++) {
		if (await predicate()) return;
		await realDelay(25);
	}
	assert.fail('Expected state was not reached');
}

export function mockTimeouts(t: TestContext) {
	t.mock.timers.enable({ apis: ['setTimeout'] });
	syncBuiltinESMExports();
	t.after(() => {
		t.mock.timers.reset();
		syncBuiltinESMExports();
	});
}

import { syncBuiltinESMExports } from 'node:module';
import { setTimeout } from 'node:timers/promises';
import type { TestContext } from 'node:test';

// Poll real subprocess I/O while application timers advance only when the test asks.
export const realDelay = setTimeout;

export function mockTimeouts(t: TestContext) {
	t.mock.timers.enable({ apis: ['setTimeout'] });
	syncBuiltinESMExports();
	t.after(() => {
		t.mock.timers.reset();
		syncBuiltinESMExports();
	});
}

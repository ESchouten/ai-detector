import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { connectTray } from './windows-tray.ts';

test('tray actions reach the owner and shutdown closes the helper', { timeout: 5000 }, async () => {
	const child = spawn('node', [
		fileURLToPath(new URL('./fixtures/windows-tray.cjs', import.meta.url))
	]);
	const actions: string[] = [];
	let resolveQuit!: () => void;
	const requested = new Promise<void>((resolve) => {
		resolveQuit = resolve;
	});
	const close = connectTray(
		child,
		() => actions.push('open'),
		() => {
			actions.push('quit');
			resolveQuit();
		}
	);
	try {
		await requested;
		assert.deepEqual(actions, ['open', 'quit']);
		assert.equal(child.exitCode, null, 'Requesting quit must leave time to drain monitoring');
		await close();
		assert.equal(child.exitCode, 0);
	} finally {
		child.kill();
	}
});

test(
	'a helper that already exited does not block application shutdown',
	{ timeout: 5000 },
	async () => {
		const child = spawn('node', ['-e', 'process.exit(0)']);
		const close = connectTray(
			child,
			() => assert.fail('unexpected open'),
			() => assert.fail('unexpected quit')
		);
		await once(child, 'close');
		await close();
	}
);

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { PassThrough } from 'node:stream';
import { connectDesktopHost } from './host.ts';

test('the native shell can request a graceful shutdown after readiness', () => {
	const input = new PassThrough();
	const output = new PassThrough();
	const reasons: string[] = [];
	const close = connectDesktopHost(
		input,
		output,
		(reason) => reasons.push(reason),
		() => {
			assert.fail('Closing our own connection is not a lost launcher');
		}
	);
	assert.equal(output.read().toString(), 'AI_DETECTOR_READY\n');
	input.write('unknown\n');
	assert.equal(reasons.length, 0);
	input.write('quit\n');
	assert.deepEqual(reasons, ['Native launcher sent an explicit quit command']);
	assert.equal(input.destroyed, false, 'The server retains time to drain monitoring');
	close();
	assert.equal(reasons.length, 1, 'Closing our own connection must not request another shutdown');
});

test('losing the native shell reports the disconnect without requesting shutdown', async () => {
	const input = new PassThrough();
	const output = new PassThrough();
	await new Promise<void>((resolve) => {
		connectDesktopHost(input, output, () => assert.fail('Monitoring must keep running'), resolve);
		input.end();
	});
});

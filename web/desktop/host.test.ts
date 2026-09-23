import assert from 'node:assert/strict';
import { test } from 'node:test';
import { PassThrough } from 'node:stream';
import { connectDesktopHost } from './host.ts';

test('the native shell can request a graceful shutdown after readiness', () => {
	const input = new PassThrough();
	const output = new PassThrough();
	let quits = 0;
	const close = connectDesktopHost(input, output, () => quits++);
	assert.equal(output.read().toString(), 'AI_DETECTOR_READY\n');
	input.write('unknown\n');
	assert.equal(quits, 0);
	input.write('quit\n');
	assert.equal(quits, 1);
	assert.equal(input.destroyed, false, 'The server retains time to drain monitoring');
	close();
	assert.equal(quits, 1, 'Closing our own connection must not request another shutdown');
});

test('a native shell that closes its pipe does not orphan monitoring', async () => {
	const input = new PassThrough();
	const output = new PassThrough();
	await new Promise<void>((resolve) => {
		connectDesktopHost(input, output, resolve);
		input.end();
	});
});

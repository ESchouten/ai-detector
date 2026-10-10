import assert from 'node:assert/strict';
import { once } from 'node:events';
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import type { TestContext } from 'node:test';

/** The address of a local HTTP server that is closed after the test. */
export async function server(
	t: TestContext,
	handler: (request: IncomingMessage, response: ServerResponse) => void
) {
	const instance = createServer(handler).listen(0, '127.0.0.1');
	await once(instance, 'listening');
	t.after(async () => {
		instance.closeAllConnections();
		await new Promise<void>((resolve) => instance.close(() => resolve()));
	});
	const address = instance.address();
	assert.ok(address && typeof address !== 'string');
	return `http://127.0.0.1:${address.port}`;
}

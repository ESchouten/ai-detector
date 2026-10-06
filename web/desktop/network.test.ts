import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { setImmediate } from 'node:timers/promises';
import { test } from 'node:test';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import ciao, { type ServiceOptions } from '@homebridge/ciao';
import { advertiseDashboard } from './network.ts';

test('dashboard uses aidetector.local and reports the name selected after a conflict', async (t) => {
	let hostname = 'aidetector.local.';
	const service = Object.assign(new EventEmitter(), {
		getHostname: () => hostname,
		advertise: async () => {},
		destroy: t.mock.fn(async () => {})
	});
	const shutdown = Promise.withResolvers<void>();
	const responder = {
		createService(options: ServiceOptions) {
			assert.equal(options.hostname, 'aidetector');
			assert.equal(options.type, 'http');
			assert.equal(options.port, 80);
			assert.equal(options.disabledIpv6, true);
			return service;
		},
		shutdown: t.mock.fn(() => shutdown.promise)
	};
	t.mock.method(ciao, 'getResponder', () => responder);
	const info = t.mock.method(console, 'info', () => {});
	const close = advertiseDashboard(80);
	await setImmediate();
	assert.ok(
		info.mock.calls.some(({ arguments: args }) => args[0] === 'LAN name: http://aidetector.local')
	);
	hostname = 'ai-detector-(2).local.';
	service.emit('hostname-change', 'ai-detector-(2)');
	assert.equal(info.mock.calls.at(-1)?.arguments[0], 'LAN name: http://ai-detector-(2).local');
	let closed = false;
	const closing = close().then(() => {
		closed = true;
	});
	await setImmediate();
	assert.equal(closed, false);
	shutdown.resolve();
	await closing;
	assert.equal(responder.shutdown.mock.callCount(), 1);
	assert.equal(service.destroy.mock.callCount(), 1);
});

test('optional discovery errors are logged without failing application shutdown', async (t) => {
	const unavailable = new Error('Multicast unavailable');
	const service = Object.assign(new EventEmitter(), {
		getHostname: () => 'aidetector.local.',
		advertise: async () => {
			throw unavailable;
		},
		destroy: async () => {}
	});
	t.mock.method(ciao, 'getResponder', () => ({
		createService: () => service,
		shutdown: async () => {
			throw unavailable;
		}
	}));
	t.mock.method(console, 'info', () => {});
	const warn = t.mock.method(console, 'warn', () => {});
	const close = advertiseDashboard(80);
	await setImmediate();
	await assert.doesNotReject(close);
	assert.deepEqual(
		warn.mock.calls.map(({ arguments: args }) => args),
		[
			['LAN discovery unavailable:', unavailable],
			['LAN discovery shutdown failed:', unavailable]
		]
	);
});

test('closing discovery during initialization leaves no active network sockets', async () => {
	const module = JSON.stringify(new URL('./network.ts', import.meta.url).href);
	const { stdout } = await promisify(execFile)(
		process.execPath,
		[
			'--input-type=module',
			'-e',
			`import { advertiseDashboard } from ${module};
			await advertiseDashboard(80)();
			console.log('Discovery closed');`
		],
		{ timeout: 10000 }
	);
	assert.match(stdout, /Discovery closed/);
});

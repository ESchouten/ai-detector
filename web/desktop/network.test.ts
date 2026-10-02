import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { setImmediate } from 'node:timers/promises';
import { test } from 'node:test';
import ciao, { type ServiceOptions } from '@homebridge/ciao';
import { advertiseDashboard } from './network.ts';

test('dashboard uses ai-detector.local and reports the name selected after a conflict', async (t) => {
	let hostname = 'ai-detector.local.';
	const service = Object.assign(new EventEmitter(), {
		getHostname: () => hostname,
		advertise: async () => {}
	});
	const shutdown = Promise.withResolvers<void>();
	const responder = {
		createService(options: ServiceOptions) {
			assert.equal(options.hostname, 'ai-detector');
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
		info.mock.calls.some(({ arguments: args }) => args[0] === 'LAN name: http://ai-detector.local')
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
});

test('optional discovery errors are logged without failing application shutdown', async (t) => {
	const unavailable = new Error('Multicast unavailable');
	const service = Object.assign(new EventEmitter(), {
		getHostname: () => 'ai-detector.local.',
		advertise: async () => {
			throw unavailable;
		}
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

import assert from 'node:assert/strict';
import { setImmediate } from 'node:timers/promises';
import { test } from 'node:test';
import {
	connectCameraBatch,
	type BatchCamera,
	type BatchConnection
} from '../src/lib/camera-batch.ts';

function deferred<T>() {
	let resolve!: (value: T) => void;
	let reject!: (cause: Error) => void;
	const promise = new Promise<T>((yes, no) => {
		resolve = yes;
		reject = no;
	});
	return { promise, resolve, reject };
}

function camera(address: string): BatchCamera {
	return { address, name: address, state: 'waiting' };
}

const login = { username: 'camera-user', password: 'fixture-password' };
const connection: BatchConnection = {
	source: 'rtsp://camera-user:fixture-password@camera.test/stream',
	profiles: [
		{ token: 'first', name: 'Entrance' },
		{ token: 'second', name: 'Yard' }
	],
	connection: { address: 'http://camera.test/onvif', profileToken: 'first' }
};

test('batch connections are bounded, keep independent successes and retain channel choices', async () => {
	const queue = [camera('one'), camera('two'), camera('three')];
	const jobs = queue.map(() => deferred<BatchConnection>());
	const started: string[] = [];
	const result = new Map<string, BatchCamera>();
	const work = connectCameraBatch(
		queue,
		login,
		({ address }) => {
			started.push(address);
			return jobs[queue.findIndex((camera) => camera.address === address)].promise;
		},
		(camera) => result.set(camera.address, camera),
		new AbortController().signal
	);
	assert.deepEqual(started, ['one', 'two']);
	jobs[0].resolve(connection);
	await setImmediate();
	assert.deepEqual(started, ['one', 'two', 'three']);
	jobs[1].reject(new Error('Check the second camera login.'));
	jobs[2].resolve(connection);
	await work;
	assert.equal(result.get('one')?.state, 'ready');
	assert.deepEqual(result.get('one')?.connection?.profiles, connection.profiles);
	assert.deepEqual(result.get('one')?.login, login);
	assert.equal(result.get('two')?.state, 'failed');
	assert.equal(result.get('two')?.error, 'Check the second camera login.');
	assert.equal(result.get('three')?.state, 'ready');
	assert.ok([...result.values()].every((camera) => camera.savedId === undefined));
});

test('retry only connects failures and keeps ready, saved and skipped cameras untouched', async () => {
	const ready: BatchCamera = {
		...camera('ready'),
		state: 'ready',
		connection,
		login,
		profileToken: 'second'
	};
	const saved: BatchCamera = { ...camera('saved'), state: 'saved', savedId: 'stable-camera-id' };
	const skipped: BatchCamera = { ...ready, address: 'skipped', state: 'skipped' };
	const queue: BatchCamera[] = [ready, saved, skipped, { ...camera('failed'), state: 'failed' }];
	const before = structuredClone(queue);
	const updates: BatchCamera[] = [];
	const retryLogin = { ...login, password: 'corrected-password' };
	await connectCameraBatch(
		queue,
		retryLogin,
		async (input) => {
			assert.deepEqual(input, { ...retryLogin, address: 'failed' });
			return connection;
		},
		(camera) => updates.push(camera),
		new AbortController().signal
	);
	assert.deepEqual(
		updates.map((camera) => [camera.address, camera.state]),
		[
			['failed', 'connecting'],
			['failed', 'ready']
		]
	);
	assert.deepEqual(updates[1].login, retryLogin);
	assert.deepEqual(queue, before);
});

test('leaving batch setup ignores late connections and does not start the remaining queue', async () => {
	const pending = deferred<BatchConnection>();
	const controller = new AbortController();
	const started: string[] = [];
	const updates: BatchCamera[] = [];
	const work = connectCameraBatch(
		[camera('one'), camera('two'), camera('three')],
		login,
		({ address }) => {
			started.push(address);
			return pending.promise;
		},
		(camera) => updates.push(camera),
		controller.signal
	);
	controller.abort();
	pending.resolve(connection);
	await work;
	assert.deepEqual(started, ['one', 'two']);
	assert.deepEqual(
		updates.map((camera) => camera.state),
		['connecting', 'connecting']
	);
});

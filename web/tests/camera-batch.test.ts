import assert from 'node:assert/strict';
import { setImmediate } from 'node:timers/promises';
import { test } from 'node:test';
import {
	connectCameraBatch,
	type BatchCamera,
	type CheckedConnection
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

const found = (address: string) => ({ address, name: address });
function camera(address: string): BatchCamera {
	return { ...found(address), state: 'waiting' };
}

const login = { username: 'camera-user', password: 'fixture-password' };
const source = 'rtsp://camera-user:fixture-password@camera.test/stream';
const connection: CheckedConnection = {
	source,
	profiles: [
		{ token: 'first', name: 'Entrance' },
		{ token: 'second', name: 'Yard' }
	],
	connection: { address: 'http://camera.test/onvif', profileToken: 'first' },
	check: {
		source,
		checkId: 'checked-camera',
		checkedAt: '2026-09-22T10:00:00.000Z',
		previewUrl: '/camera-checks/checked-camera/picture.jpg',
		recordingUrl: '/camera-checks/checked-camera/recording.mp4',
		profiles: []
	}
};

test('batch connections are bounded, keep independent successes and retain channel choices', async () => {
	const queue = [camera('one'), camera('two'), camera('three')];
	const jobs = queue.map(() => deferred<CheckedConnection>());
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
	// A connected camera keeps its picture check, its other streams and the login that reached it.
	assert.deepEqual(result.get('one'), {
		...camera('one'),
		state: 'ready',
		connection: { ...connection, login },
		error: undefined
	});
	assert.equal(result.get('two')?.state, 'failed');
	assert.equal(result.get('two')?.error, 'Check the second camera login.');
	assert.equal(result.get('three')?.state, 'ready');
	assert.ok([...result.values()].every((camera) => camera.state !== 'saved'));
});

test('retry only connects failures and keeps ready and saved cameras untouched', async () => {
	const ready: BatchCamera = { ...found('ready'), state: 'ready', connection };
	const saved: BatchCamera = {
		...found('saved'),
		state: 'saved',
		connection,
		savedId: 'stable-camera-id'
	};
	// A camera whose refreshed picture failed still shows the one that worked before.
	const failed: BatchCamera = {
		...found('failed'),
		state: 'failed',
		connection,
		error: 'Could not check this picture. Try again.'
	};
	const queue: BatchCamera[] = [ready, saved, failed];
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
		updates.map((camera) => [camera.address, camera.state, camera.error, !!camera.connection]),
		[
			['failed', 'connecting', undefined, true],
			['failed', 'ready', undefined, true]
		]
	);
	assert.deepEqual(updates[1].connection?.login, retryLogin);
	assert.deepEqual(queue, before);
});

test('leaving batch setup ignores late connections and does not start the remaining queue', async () => {
	const pending = deferred<CheckedConnection>();
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

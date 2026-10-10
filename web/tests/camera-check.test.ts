import assert from 'node:assert/strict';
import { once } from 'node:events';
import { test } from 'node:test';
import { checkCameraRecording, checkConnection } from '../src/lib/camera-check.ts';
import { server } from './support/http.ts';

test('recording check sends the resolved source and reads the checked camera result', async (t) => {
	const source = 'rtsp://camera.example.test/live';
	const result = {
		source,
		checkId: 'checked-camera',
		previewUrl: '/camera-checks/checked-camera/picture.jpg'
	};
	const endpoint = await server(t, async (request, response) => {
		assert.equal(request.method, 'POST');
		assert.equal(request.headers['content-type'], 'application/json');
		const chunks = [];
		for await (const chunk of request) chunks.push(chunk);
		assert.deepEqual(JSON.parse(Buffer.concat(chunks).toString()), { source });
		response.writeHead(200, { 'Content-Type': 'application/json' });
		response.end(JSON.stringify(result));
	});
	assert.deepEqual(
		await checkCameraRecording(source, new AbortController().signal, endpoint),
		result
	);
});

test('a checked connection keeps what the camera answered and takes the source that worked', async (t) => {
	const answered = {
		source: 'rtsp://camera.example.test/live',
		profiles: [{ token: 'main', name: 'Main stream' }],
		connection: { address: 'http://camera.example.test/onvif' }
	};
	const check = {
		source: 'rtsp://camera.example.test/live?transport=tcp',
		checkId: 'checked-camera',
		previewUrl: '/camera-checks/checked-camera/picture.jpg'
	};
	let requests = 0;
	const endpoint = await server(t, (_request, response) => {
		requests++;
		response.writeHead(200, { 'Content-Type': 'application/json' });
		response.end(JSON.stringify(check));
	});
	assert.deepEqual(await checkConnection(answered, new AbortController().signal, endpoint), {
		...answered,
		source: check.source,
		check
	});
	// Leaving the page between the camera's answer and its picture check starts no check.
	const left = new AbortController();
	left.abort();
	await assert.rejects(checkConnection(answered, left.signal, endpoint), { name: 'AbortError' });
	assert.equal(requests, 1);
});

test('recording check displays expected camera errors and a useful message for server failures', async (t) => {
	let status = 400;
	const endpoint = await server(t, (_request, response) => {
		response.writeHead(status, {
			'Content-Type': status === 400 ? 'application/json' : 'text/html'
		});
		response.end(
			status === 400 ? JSON.stringify({ message: 'Camera login rejected.' }) : '<h1>Error</h1>'
		);
	});
	const signal = new AbortController().signal;
	await assert.rejects(
		checkCameraRecording('rtsp://camera/live', signal, endpoint),
		/Camera login rejected/
	);
	status = 500;
	await assert.rejects(
		checkCameraRecording('rtsp://camera/live', signal, endpoint),
		/check could not finish/
	);
});

test(
	'cancelling the recording check closes its real HTTP request before the server replies',
	{ timeout: 5000 },
	async (t) => {
		const started = Promise.withResolvers<void>();
		const closed = Promise.withResolvers<void>();
		const endpoint = await server(t, async (request, response) => {
			response.once('close', closed.resolve);
			request.resume();
			await once(request, 'end');
			started.resolve();
		});
		const controller = new AbortController();
		const pending = checkCameraRecording('rtsp://camera/live', controller.signal, endpoint);
		await started.promise;
		controller.abort();
		await assert.rejects(pending, { name: 'AbortError' });
		await closed.promise;
	}
);

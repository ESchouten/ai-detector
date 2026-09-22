import assert from 'node:assert/strict';
import { once } from 'node:events';
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { test, type TestContext } from 'node:test';
import { checkCameraRecording } from '../src/lib/camera-check.ts';

async function serve(
	t: TestContext,
	handler: (request: IncomingMessage, response: ServerResponse) => void
) {
	const server = createServer(handler).listen(0, '127.0.0.1');
	await once(server, 'listening');
	t.after(async () => {
		server.closeAllConnections();
		await new Promise<void>((resolve) => server.close(() => resolve()));
	});
	const address = server.address();
	assert.ok(address && typeof address !== 'string');
	return `http://127.0.0.1:${address.port}/camera-checks`;
}

test('recording check sends the resolved source and reads the checked camera result', async (t) => {
	const source = 'rtsp://camera.example.test/live';
	const result = {
		source,
		checkId: 'checked-camera',
		checkedAt: new Date().toISOString(),
		previewUrl: '/camera-checks/checked-camera/picture.jpg',
		recordingUrl: '/camera-checks/checked-camera/recording.mp4',
		profiles: []
	};
	const endpoint = await serve(t, async (request, response) => {
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

test('recording check displays expected camera errors and a useful message for server failures', async (t) => {
	let status = 400;
	const endpoint = await serve(t, (_request, response) => {
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
		let connected!: () => void;
		let disconnected!: () => void;
		const started = new Promise<void>((resolve) => {
			connected = resolve;
		});
		const closed = new Promise<void>((resolve) => {
			disconnected = resolve;
		});
		const endpoint = await serve(t, async (request, response) => {
			response.once('close', disconnected);
			request.resume();
			await once(request, 'end');
			connected();
		});
		const controller = new AbortController();
		const pending = checkCameraRecording('rtsp://camera/live', controller.signal, endpoint);
		await started;
		controller.abort();
		await assert.rejects(pending, { name: 'AbortError' });
		await closed;
	}
);

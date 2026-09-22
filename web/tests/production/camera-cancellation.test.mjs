import assert from 'node:assert/strict';
import { execFile, spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdtemp, readFile, readdir, rm } from 'node:fs/promises';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { promisify } from 'node:util';
import ffmpeg from 'ffmpeg-static';

const entry = new URL('../../node-server.mjs', import.meta.url).href;
const adapter = new URL('../../build/index.js', import.meta.url).href;

async function application(t, directory) {
	const env = {
		...process.env,
		HOST: '127.0.0.1',
		PORT: '0',
		AIDETECTOR_DATA_DIR: directory,
		FFMPEG_PATH: ffmpeg,
		SHUTDOWN_TIMEOUT: '2'
	};
	for (const name of [
		'ORIGIN',
		'PROTOCOL_HEADER',
		'HOST_HEADER',
		'PORT_HEADER',
		'SOCKET_PATH',
		'LISTEN_PID',
		'LISTEN_FDS',
		'AIDETECTOR_EXECUTABLE'
	])
		delete env[name];
	const child = spawn(
		process.execPath,
		[
			'--input-type=module',
			'--eval',
			`
		import { once } from 'node:events';
		await import(${JSON.stringify(entry)});
		const { server } = await import(${JSON.stringify(adapter)});
		if (!server.server.listening) await once(server.server, 'listening');
		process.send({ port: server.server.address().port });
		process.disconnect();
	`
		],
		{ cwd: directory, env, stdio: ['ignore', 'pipe', 'pipe', 'ipc'] }
	);
	let logs = '';
	child.stdout.on('data', (chunk) => {
		logs += chunk;
	});
	child.stderr.on('data', (chunk) => {
		logs += chunk;
	});
	const exited = once(child, 'exit');
	t.after(async () => {
		const deadline = setTimeout(() => child.kill('SIGKILL'), 5000);
		try {
			child.kill('SIGTERM');
			await exited;
		} finally {
			clearTimeout(deadline);
		}
	});
	const [{ port }] = await once(child, 'message', { signal: AbortSignal.timeout(10000) });
	return { base: `http://127.0.0.1:${port}`, logs: () => logs };
}

async function camera(t, directory) {
	const sample = path.join(directory, 'camera.mp4');
	await promisify(execFile)(ffmpeg, [
		'-hide_banner',
		'-loglevel',
		'error',
		'-f',
		'lavfi',
		'-i',
		'testsrc2=size=320x240:rate=12',
		'-t',
		'3',
		'-c:v',
		'libx264',
		'-pix_fmt',
		'yuv420p',
		'-movflags',
		'+faststart',
		sample
	]);
	const bytes = await readFile(sample);
	let connected;
	let disconnected;
	const started = new Promise((resolve) => {
		connected = resolve;
	});
	const closed = new Promise((resolve) => {
		disconnected = resolve;
	});
	const server = createServer((request, response) => {
		if (request.url === '/hanging') {
			response.once('close', disconnected);
			connected();
			return;
		}
		response.writeHead(200, { 'Content-Type': 'video/mp4', 'Content-Length': bytes.length });
		response.end(bytes);
	}).listen(0, '127.0.0.1');
	await once(server, 'listening');
	t.after(async () => {
		server.closeAllConnections();
		await new Promise((resolve) => server.close(resolve));
	});
	return { base: `http://127.0.0.1:${server.address().port}`, started, closed };
}

test(
	'production recording check cancellation stops FFmpeg after body consumption and permits immediate retry',
	{ timeout: 20000 },
	async (t) => {
		const directory = await mkdtemp(path.join(tmpdir(), 'camera-cancellation-production-'));
		t.after(() => rm(directory, { recursive: true, force: true }));
		const app = await application(t, directory);
		const source = await camera(t, directory);
		const controller = new AbortController();
		const check = (url, signal) =>
			fetch(`${app.base}/camera-checks`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json', Origin: app.base },
				body: JSON.stringify({ source: url }),
				signal
			});
		const pending = check(`${source.base}/hanging`, controller.signal);
		// FFmpeg reaching the camera proves the complete browser JSON body was already consumed.
		await source.started;
		const cancelledAt = Date.now();
		controller.abort();
		await assert.rejects(pending, { name: 'AbortError' });
		await source.closed;
		assert.ok(
			Date.now() - cancelledAt < 2000,
			'FFmpeg must stop on disconnect, not its 10-second read timeout'
		);
		const retried = await check(`${source.base}/working`);
		assert.equal(retried.status, 200, await retried.clone().text());
		const result = await retried.json();
		assert.equal(result.source, `${source.base}/working`);
		assert.equal((await fetch(`${app.base}${result.previewUrl}`)).status, 200);
		assert.deepEqual(await readdir(path.join(directory, '.camera-checks')), [result.checkId]);
		assert.doesNotMatch(app.logs(), /AbortError|The operation was aborted|Internal Error/);
	}
);

import { execFile, spawn } from 'node:child_process';
import { once } from 'node:events';
import { createServer } from 'node:http';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import ffmpeg from 'ffmpeg-static';

const entry = new URL('../../node-server.mjs', import.meta.url).href;
const adapter = new URL('../../build/index.js', import.meta.url).href;
const executable = fileURLToPath(new URL('../fixtures/detector.mjs', import.meta.url));

export async function startServer(t, origin, prepare, presetsUrl = '') {
	const directory = await mkdtemp(path.join(tmpdir(), 'detector-node-production-'));
	await prepare?.(directory);
	const env = {
		...process.env,
		HOST: '127.0.0.1',
		PORT: '0',
		AIDETECTOR_DATA_DIR: directory,
		AIDETECTOR_EXECUTABLE: executable,
		// No test asks the published presets on GitHub; one names a stand-in for them.
		AIDETECTOR_PRESETS_URL: presetsUrl,
		SHUTDOWN_TIMEOUT: '2'
	};
	for (const name of [
		'ORIGIN',
		'HOST_HEADER',
		'PORT_HEADER',
		'SOCKET_PATH',
		'AIDETECTOR_PRESETS',
		'LISTEN_PID',
		'LISTEN_FDS'
	])
		delete env[name];
	if (origin) env.ORIGIN = origin;
	// Use the adapter's public server export to discover its OS-assigned test port.
	const script = `
		import { once } from 'node:events';
		await import(${JSON.stringify(entry)});
		const { server } = await import(${JSON.stringify(adapter)});
		if (!server.server.listening) await once(server.server, 'listening');
		process.send({ port: server.server.address().port });
		process.disconnect();
	`;
	const child = spawn(process.execPath, ['--input-type=module', '--eval', script], {
		cwd: directory,
		env,
		stdio: ['ignore', 'pipe', 'pipe', 'ipc']
	});
	let logs = '';
	child.stdout.on('data', (chunk) => {
		logs += chunk;
	});
	child.stderr.on('data', (chunk) => {
		logs += chunk;
	});
	const exited = once(child, 'exit');
	async function stop() {
		const deadline = setTimeout(() => child.kill('SIGKILL'), 5000);
		try {
			if (child.exitCode === null && child.signalCode === null) child.kill('SIGTERM');
			return await exited;
		} finally {
			clearTimeout(deadline);
		}
	}
	t.after(async () => {
		await stop();
		await rm(directory, { recursive: true, force: true });
	});
	const [{ port }] = await once(child, 'message', { signal: AbortSignal.timeout(10000) });
	return { directory, base: `http://127.0.0.1:${port}`, stop, logs: () => logs };
}

/** A camera that answers with a short sample video, except where `intercept` takes the request. */
export async function cameraSource(t, directory, intercept) {
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
	const camera = createServer((request, response) => {
		if (intercept?.(request, response)) return;
		response.writeHead(200, { 'Content-Type': 'video/mp4', 'Content-Length': bytes.length });
		response.end(bytes);
	}).listen(0, '127.0.0.1');
	await once(camera, 'listening');
	t.after(async () => {
		camera.closeAllConnections();
		await new Promise((resolve) => camera.close(resolve));
	});
	return `http://127.0.0.1:${camera.address().port}/pen`;
}

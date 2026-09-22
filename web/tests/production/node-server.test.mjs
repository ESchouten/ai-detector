import assert from 'node:assert/strict';
import { execFile, spawn } from 'node:child_process';
import { once } from 'node:events';
import { createServer, request } from 'node:http';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { setTimeout as delay } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import { parse, stringify } from 'devalue';
import ffmpeg from 'ffmpeg-static';
import { manifest } from '../../build/server/manifest.js';

const entry = new URL('../../node-server.mjs', import.meta.url).href;
const adapter = new URL('../../build/index.js', import.meta.url).href;
const executable = fileURLToPath(new URL('../fixtures/detector.mjs', import.meta.url));
const commands = {};
for (const [id, load] of Object.entries(manifest._.remotes)) {
	const { default: remote } = await load();
	for (const name of ['startDetector', 'getCameraConnection', 'saveCamera']) {
		if (name in remote) commands[name] = `/${manifest.appPath}/remote/${id}/${name}`;
	}
}
assert.ok(
	commands.saveCamera && commands.getCameraConnection && commands.startDetector,
	'Build is missing setup/runtime commands'
);

// Match SvelteKit's wire encoding, using its serialization library for nested results too.
function commandBody(input) {
	return JSON.stringify({
		payload: Buffer.from(stringify(input)).toString('base64url'),
		refreshes: []
	});
}
const startBody = commandBody('native');

// Unlike fetch, node:http permits the explicit LAN Host header used by this transport test.
function send(url, { method = 'GET', headers, body } = {}) {
	return new Promise((resolve, reject) => {
		const outgoing = request(url, { method, headers }, (incoming) => {
			const chunks = [];
			incoming.on('data', (chunk) => chunks.push(chunk));
			incoming.on('end', () =>
				resolve(
					new Response(Buffer.concat(chunks), {
						status: incoming.statusCode,
						headers: incoming.headers
					})
				)
			);
			incoming.on('error', reject);
		});
		outgoing.on('error', reject);
		outgoing.end(body);
	});
}

async function startServer(t, origin) {
	const directory = await mkdtemp(path.join(tmpdir(), 'detector-node-production-'));
	const env = {
		...process.env,
		HOST: '127.0.0.1',
		PORT: '0',
		AIDETECTOR_DATA_DIR: directory,
		AIDETECTOR_EXECUTABLE: executable,
		SHUTDOWN_TIMEOUT: '2'
	};
	for (const name of [
		'ORIGIN',
		'PROTOCOL_HEADER',
		'HOST_HEADER',
		'PORT_HEADER',
		'SOCKET_PATH',
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

async function cameraSource(t, directory) {
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
	const camera = createServer((_request, response) => {
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

for (const deployment of ['local HTTP', 'LAN HTTP', 'HTTPS proxy']) {
	test(
		`production ${deployment} setup protects origins and drains the detector on shutdown`,
		{
			skip: process.platform === 'win32',
			timeout: 20000
		},
		async (t) => {
			const publicOrigin =
				deployment === 'HTTPS proxy' ? 'https://detector.example.test' : undefined;
			const { directory, base, stop, logs } = await startServer(t, publicOrigin);
			const source = await cameraSource(t, directory);
			const cameraInput = { label: 'Barn camera', source, preset: 'general' };
			const host = deployment === 'LAN HTTP' ? 'barn.local:8080' : new URL(base).host;
			const origin = publicOrigin ?? `http://${host}`;
			const page = await send(`${base}/setup`, { headers: { Host: host } });
			assert.equal(page.status, 200);
			assert.ok((await page.text()).includes('<title>Setup · AI Detector</title>'));
			const headers = {
				Host: host,
				Origin: origin,
				'Content-Type': 'application/json',
				'x-sveltekit-pathname': '/setup',
				'x-sveltekit-search': '',
				'x-ai-detector-protocol': 'https',
				'x-forwarded-proto': 'https'
			};
			const rejected = await send(base + commands.saveCamera, {
				method: 'POST',
				body: commandBody(cameraInput),
				headers: {
					...headers,
					Origin: `https://${host}` === origin ? 'https://other.example.test' : `https://${host}`
				}
			});
			assert.equal(rejected.status, 403, await rejected.text());
			const rejectedCheck = await send(base + '/camera-checks', {
				method: 'POST',
				body: JSON.stringify({ source }),
				headers: { ...headers, Origin: 'https://other.example.test' }
			});
			assert.equal(rejectedCheck.status, 403, await rejectedCheck.text());
			await assert.rejects(readFile(path.join(directory, 'config.json')), { code: 'ENOENT' });
			const checked = await send(base + '/camera-checks', {
				method: 'POST',
				headers,
				body: JSON.stringify({ source })
			});
			assert.equal(checked.status, 200, await checked.clone().text());
			const { checkId } = await checked.json();
			const saved = await send(base + commands.saveCamera, {
				method: 'POST',
				body: commandBody({ ...cameraInput, checkId }),
				headers
			});
			assert.equal(saved.status, 200, await saved.clone().text());
			assert.equal((await saved.json()).type, 'result');
			const config = JSON.parse(await readFile(path.join(directory, 'config.json'), 'utf8'));
			assert.deepEqual(config.detectors[0].detection.source, [source]);
			const app = JSON.parse(await readFile(path.join(directory, 'app.json'), 'utf8'));
			const archiveCheck = `${base}/cameras/${app.streams[0].id}/archive-check`;
			const rejectedArchive = await send(archiveCheck, {
				method: 'POST',
				body: JSON.stringify({ checkId }),
				headers: { ...headers, Origin: 'https://other.example.test' }
			});
			assert.equal(rejectedArchive.status, 403, await rejectedArchive.text());
			const checkedArchive = await send(archiveCheck, {
				method: 'POST',
				body: JSON.stringify({ checkId }),
				headers
			});
			assert.equal(checkedArchive.status, 200, await checkedArchive.clone().text());
			const { verifiedAt } = await checkedArchive.json();
			assert.ok(Number.isFinite(Date.parse(verifiedAt)));
			const checkedApp = JSON.parse(await readFile(path.join(directory, 'app.json'), 'utf8'));
			assert.equal(checkedApp.streams[0].setup.archiveVerifiedAt, verifiedAt);
			const started = await send(base + commands.startDetector, {
				method: 'POST',
				body: startBody,
				headers
			});
			assert.equal(started.status, 200);
			await started.arrayBuffer();
			for (let i = 0; i < 100; i++) {
				try {
					await readFile(path.join(directory, 'starts.txt'));
					break;
				} catch (error) {
					if (error.code !== 'ENOENT') throw error;
				}
				await delay(20);
			}
			assert.equal(await readFile(path.join(directory, 'starts.txt'), 'utf8'), 'started\n');
			assert.deepEqual(await stop(), [0, null], logs());
			assert.equal(await readFile(path.join(directory, 'flushed.txt'), 'utf8'), 'flushed');
		}
	);
}

test(
	'production camera onboarding verifies playable media and assigns each camera atomically',
	{ skip: process.platform === 'win32', timeout: 20000 },
	async (t) => {
		const { directory, base } = await startServer(t);
		const source = await cameraSource(t, directory);
		const headers = {
			Origin: base,
			'Content-Type': 'application/json',
			'x-sveltekit-pathname': '/setup',
			'x-sveltekit-search': ''
		};
		async function command(name, input) {
			const response = await send(base + commands[name], {
				method: 'POST',
				headers,
				body: commandBody(input)
			});
			assert.equal(response.status, 200, await response.clone().text());
			return response.json();
		}
		const unverified = await command('saveCamera', { label: 'Pen', source, preset: 'general' });
		assert.equal(unverified.type, 'error');
		assert.equal(unverified.status, 400);
		await assert.rejects(readFile(path.join(directory, 'config.json')), { code: 'ENOENT' });
		async function checkCamera(source) {
			const response = await send(base + '/camera-checks', {
				method: 'POST',
				headers,
				body: JSON.stringify({ source })
			});
			assert.equal(response.status, 200, await response.clone().text());
			return response.json();
		}
		const result = await checkCamera(source);
		assert.ok(result.checkId);
		const preview = await send(base + result.previewUrl);
		assert.equal(preview.status, 200);
		assert.equal(preview.headers.get('content-type'), 'image/jpeg');
		assert.equal(preview.headers.get('cache-control'), 'no-store');
		assert.equal(
			Buffer.from(await preview.arrayBuffer())
				.subarray(0, 2)
				.toString('hex'),
			'ffd8'
		);
		const clip = await send(base + result.recordingUrl, { headers: { range: 'bytes=0-15' } });
		assert.equal(clip.status, 206);
		assert.equal((await clip.arrayBuffer()).byteLength, 16);
		const saved = await command('saveCamera', {
			label: 'Pen',
			source: result.source,
			preset: 'general',
			checkId: result.checkId
		});
		assert.equal(saved.type, 'result', JSON.stringify(saved));
		const id = parse(saved.result).id;
		const renamed = await command('saveCamera', {
			id,
			label: 'Calving pen',
			source: result.source,
			preset: 'keep'
		});
		assert.equal(renamed.type, 'result', JSON.stringify(renamed));
		const other = await checkCamera(source + '-yard');
		assert.equal(
			(
				await command('saveCamera', {
					label: 'Yard',
					source: other.source,
					preset: 'general',
					checkId: other.checkId
				})
			).type,
			'result'
		);
		const config = JSON.parse(await readFile(path.join(directory, 'config.json'), 'utf8'));
		const app = JSON.parse(await readFile(path.join(directory, 'app.json'), 'utf8'));
		assert.equal(app.streams.length, 2);
		assert.equal(app.streams[0].id, id);
		assert.equal(app.streams[0].label, 'Calving pen');
		assert.deepEqual(
			config.detectors.map((rule) => rule.detection.source),
			[[source], [source + '-yard']]
		);
		const page = await send(`${base}/streams`);
		const html = await page.text();
		assert.ok(html.includes('Calving pen') && html.includes('Yard'));
		assert.ok(!html.includes(`/streams/${encodeURIComponent(source)}`));
	}
);

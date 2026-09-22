import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { request } from 'node:http';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { setTimeout as delay } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';
import { manifest } from '../../build/server/manifest.js';

const entry = new URL('../../node-server.mjs', import.meta.url).href;
const adapter = new URL('../../build/index.js', import.meta.url).href;
const executable = fileURLToPath(new URL('../fixtures/detector.mjs', import.meta.url));
const commands = {};
for (const [id, load] of Object.entries(manifest._.remotes)) {
	const { default: remote } = await load();
	for (const name of ['finishSetup', 'startDetector']) {
		if (name in remote) commands[name] = `/${manifest.appPath}/remote/${id}/${name}`;
	}
}
assert.ok(
	commands.finishSetup && commands.startDetector,
	'Build is missing setup/runtime commands'
);

// SvelteKit encodes these scalar command arguments as base64url devalue tuples.
const setupBody = JSON.stringify({
	payload: Buffer.from(
		JSON.stringify([
			{ label: 1, source: 2, preset: 3 },
			'Barn camera',
			'rtsp://camera.invalid/live',
			'general'
		])
	).toString('base64url'),
	refreshes: []
});
const startBody = JSON.stringify({
	payload: Buffer.from(JSON.stringify(['native'])).toString('base64url'),
	refreshes: []
});

// Unlike fetch, node:http permits the explicit LAN Host header used by this transport test.
function send(url, { method = 'GET', headers, body } = {}) {
	return new Promise((resolve, reject) => {
		const outgoing = request(url, { method, headers }, (incoming) => {
			const chunks = [];
			incoming.on('data', (chunk) => chunks.push(chunk));
			incoming.on('end', () =>
				resolve(new Response(Buffer.concat(chunks), { status: incoming.statusCode }))
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
			const rejected = await send(base + commands.finishSetup, {
				method: 'POST',
				body: setupBody,
				headers: {
					...headers,
					Origin: `https://${host}` === origin ? 'https://other.example.test' : `https://${host}`
				}
			});
			assert.equal(rejected.status, 403, await rejected.text());
			await assert.rejects(readFile(path.join(directory, 'config.json')), { code: 'ENOENT' });
			const saved = await send(base + commands.finishSetup, {
				method: 'POST',
				body: setupBody,
				headers
			});
			assert.equal(saved.status, 200, await saved.clone().text());
			assert.equal((await saved.json()).type, 'result');
			const config = JSON.parse(await readFile(path.join(directory, 'config.json'), 'utf8'));
			assert.deepEqual(config.detectors[0].detection.source, ['rtsp://camera.invalid/live']);
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

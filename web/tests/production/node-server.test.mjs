import assert from 'node:assert/strict';
import { execFile, spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { once } from 'node:events';
import { createServer, request } from 'node:http';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { setTimeout as delay } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import { parse, stringify } from 'devalue';
import ffmpeg from 'ffmpeg-static';
import { unzipSync } from 'fflate';
import { manifest } from '../../build/server/manifest.js';

const entry = new URL('../../node-server.mjs', import.meta.url).href;
const adapter = new URL('../../build/index.js', import.meta.url).href;
const executable = fileURLToPath(new URL('../fixtures/detector.mjs', import.meta.url));
const commands = {};
for (const [id, load] of Object.entries(manifest._.remotes)) {
	const { default: remote } = await load();
	for (const name of [
		'startDetector',
		'getCameraConnection',
		'saveCamera',
		'saveDetector',
		'finishSetup',
		'inspectInstallation',
		'importInstallation',
		'setLanguage'
	]) {
		if (name in remote) commands[name] = `/${manifest.appPath}/remote/${id}/${name}`;
	}
}
assert.ok(
	commands.saveCamera &&
		commands.getCameraConnection &&
		commands.startDetector &&
		commands.saveDetector &&
		commands.finishSetup,
	'Build is missing setup/runtime commands'
);

// Match SvelteKit's wire encoding, using its serialization library for nested results too.
function commandBody(input) {
	return JSON.stringify({
		payload: Buffer.from(stringify(input)).toString('base64url'),
		refreshes: []
	});
}
const startBody = commandBody(undefined);

/** What app.json records for a detector that follows a preset; takes its detection settings as ordered JSON. */
function presetVersion(settings) {
	return createHash('sha256').update(settings).digest('hex');
}

test('saved logs are searchable in the page and downloadable with conditional refreshes', async (t) => {
	const { directory, base } = await startServer(t);
	await mkdir(path.join(directory, 'logs'), { recursive: true });
	await writeFile(
		path.join(directory, 'logs/application.log'),
		'2026-09-28 20:00:00 INFO Preparing rtsp://farmer:secret@camera.local/live\n' +
			'2026-09-28 20:01:00 ERROR Invalid model\nTraceback:\n  model.py:20\n'
	);
	const response = await fetch(`${base}/logs/output`);
	assert.equal(response.status, 200);
	const text = await response.text();
	assert.match(text, /Preparing rtsp:/);
	assert.match(text, /ERROR Invalid model\nTraceback:/);
	assert.doesNotMatch(text, /secret|farmer/);
	const unchanged = await fetch(`${base}/logs/output`, {
		headers: { 'If-None-Match': response.headers.get('etag') }
	});
	assert.equal(unchanged.status, 304);
	const download = await fetch(`${base}/logs/output?download`);
	assert.match(
		download.headers.get('content-disposition'),
		/attachment; filename="ai-detector.log"/
	);
	assert.equal(await download.text(), text);
	const page = await fetch(`${base}/logs`);
	assert.equal(page.status, 200);
	assert.match(await page.text(), /Search logs/);
});

test('production downloads export filtered recordings and a separate settings backup', async (t) => {
	const { directory, base } = await startServer(t);
	const source = 'rtsp://farmer:private-password@camera.example.test/live';
	await writeFile(
		path.join(directory, 'config.json'),
		JSON.stringify({ detectors: [{ detection: { source } }] })
	);
	await writeFile(
		path.join(directory, 'app.json'),
		JSON.stringify({ streams: [{ label: 'Barn', source }] })
	);
	for (const day of ['2026-09-21', '2026-09-22']) {
		const event = path.join(directory, 'detections', 'activity', 'approved', `${day}T12-00-00`);
		await mkdir(event, { recursive: true });
		await writeFile(
			path.join(event, 'metadata.json'),
			JSON.stringify({
				timestamp: `${day}T12-00-00`,
				validated: true,
				confidence: 0.9,
				confidences: { activity: 0.9 },
				detections: 1,
				start: `${day}T12:00:00`,
				end: `${day}T12:00:02`,
				duration: 2
			})
		);
		await writeFile(path.join(event, 'clean.jpg'), `original ${day}`);
	}
	const response = await send(
		`${base}/detections/export?from=2026-09-22&to=2026-09-22&type=activity&stage=approved`
	);
	assert.equal(response.status, 200);
	assert.equal(response.headers.get('content-type'), 'application/zip');
	assert.equal(response.headers.get('cache-control'), 'no-store');
	assert.match(
		response.headers.get('content-disposition'),
		/^attachment; filename="AI-Detector-recordings-/
	);
	const files = unzipSync(new Uint8Array(await response.arrayBuffer()));
	assert.deepEqual(Object.keys(files).sort(), [
		'README.txt',
		'detections/activity/approved/2026-09-22T12-00-00/clean.jpg',
		'detections/activity/approved/2026-09-22T12-00-00/metadata.json'
	]);
	assert.equal(
		Buffer.from(files['detections/activity/approved/2026-09-22T12-00-00/clean.jpg']).toString(),
		'original 2026-09-22'
	);
	for (const query of [
		'from=invalid',
		'from=2026-09-23&to=2026-09-22',
		'type=..%2Fprivate',
		'stage=.pending'
	])
		assert.equal((await send(`${base}/detections/export?${query}`)).status, 400);
	assert.equal((await send(`${base}/detections/export?to=2025-01-01`)).status, 404);
	const backup = await send(`${base}/setup/backup`);
	assert.equal(backup.status, 200);
	assert.equal(backup.headers.get('cache-control'), 'no-store');
	const settings = unzipSync(new Uint8Array(await backup.arrayBuffer()));
	assert.deepEqual(Object.keys(settings).sort(), ['README.txt', 'app.json', 'config.json']);
	assert.equal(
		JSON.parse(Buffer.from(settings['config.json']).toString()).detectors[0].detection.source[0],
		source
	);
	await assert.rejects(readFile(path.join(directory, 'starts.txt')), { code: 'ENOENT' });
});

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

async function connectBrowser(base, origin, code) {
	const response = await send(base + '/pair', {
		method: 'POST',
		headers: {
			Host: new URL(origin).host,
			Origin: origin,
			Accept: 'text/html',
			'Content-Type': 'application/x-www-form-urlencoded'
		},
		body: new URLSearchParams({ code, name: 'Farm tablet' }).toString()
	});
	assert.equal(response.status, 303, await response.clone().text());
	assert.match(response.headers.get('set-cookie'), /; SameSite=Lax/i);
	assert.match(response.headers.get('set-cookie'), /; HttpOnly/i);
	return response.headers.get('set-cookie').split(';')[0];
}

test('remembered devices renew their cookie on the pairing page and revoked devices stay blocked', async (t) => {
	const { directory, base, logs } = await startServer(t);
	const origin = 'http://barn.local';
	const cookie = await connectBrowser(
		base,
		origin,
		logs().match(/initial pairing code: (\d{6})/)[1]
	);
	const headers = { Host: 'barn.local', Cookie: cookie, Accept: 'text/html' };
	const remembered = await send(`${base}/pair`, { headers });
	assert.equal(remembered.status, 303);
	assert.equal(remembered.headers.get('location'), '/');
	assert.equal(remembered.headers.get('set-cookie').split(';')[0], cookie);
	assert.match(remembered.headers.get('set-cookie'), /; SameSite=Lax/i);
	assert.match(remembered.headers.get('set-cookie'), /; HttpOnly/i);
	const externalPost = await send(`${base}/pair`, {
		method: 'POST',
		headers: {
			...headers,
			Origin: 'http://other.example.test',
			'Content-Type': 'application/x-www-form-urlencoded'
		},
		body: 'code=123456'
	});
	assert.equal(externalPost.status, 403);
	// A paired device invites others to the address it used itself. Only the dashboard on
	// this computer swaps in one of its own network addresses.
	const invitationLink = /href="http:\/\/([^"/:]+)(?::\d+)?\/pair#code=\d{6}"/;
	const form = { 'Content-Type': 'application/x-www-form-urlencoded' };
	const invited = await send(`${base}/devices?/connect`, {
		method: 'POST',
		headers: { ...headers, ...form, Origin: origin }
	});
	assert.equal(invited.status, 200);
	assert.equal((await invited.text()).match(invitationLink)?.[1], 'barn.local');
	const local = await send(`${base}/devices?/connect`, {
		method: 'POST',
		headers: { ...form, Origin: base, Accept: 'text/html' }
	});
	const localPage = await local.text();
	if (local.status === 200) {
		const host = localPage.match(invitationLink)?.[1];
		assert.ok(host, 'The invitation has no pairing link.');
		assert.notEqual(host, '127.0.0.1');
	} else assert.match(localPage, /Connect this computer to your local network/);
	const appPath = path.join(directory, 'app.json');
	const app = JSON.parse(await readFile(appPath, 'utf8'));
	await writeFile(appPath, JSON.stringify({ ...app, devices: [] }));
	const revoked = await send(`${base}/pair`, { headers });
	assert.equal(revoked.status, 200);
	assert.match(await revoked.text(), /Connect to AI Detector/);
	assert.equal(revoked.headers.get('set-cookie'), null);
});

async function startServer(t, origin, prepare, presetsUrl = '') {
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
		'PROTOCOL_HEADER',
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

test(
	'production import seeds setup, preserves originals and stays stopped',
	{ skip: process.platform === 'win32', timeout: 20000 },
	async (t) => {
		const { directory, base, logs } = await startServer(t);
		const previous = await mkdtemp(path.join(tmpdir(), 'previous-detector-'));
		t.after(() => rm(previous, { recursive: true, force: true }));
		const original = JSON.stringify({
			detectors: [
				{
					detection: { source: 'rtsp://camera.example.test/live' },
					yolo: { model: 'yolo11n.pt', strategy: 'LATEST' },
					exporters: { disk: { directory: 'activity' } }
				}
			]
		});
		await writeFile(path.join(previous, 'config.json'), original);
		await writeFile(
			path.join(previous, 'app.json'),
			JSON.stringify({
				streams: [{ source: 'rtsp://camera.example.test/live', label: 'Imported barn' }],
				detectors: [{ label: 'Existing detector' }]
			})
		);
		const headers = {
			Origin: base,
			'Content-Type': 'application/json',
			'x-sveltekit-pathname': '/setup',
			'x-sveltekit-search': ''
		};
		async function command(name, input, extraHeaders = {}) {
			return send(base + commands[name], {
				method: 'POST',
				headers: { ...headers, ...extraHeaders },
				body: commandBody(input)
			});
		}
		const blocked = await command('inspectInstallation', previous, {
			Origin: 'https://other.example.test'
		});
		assert.equal(blocked.status, 403);
		const remoteHost = await command('inspectInstallation', previous, {
			Host: 'farm.example.test',
			Origin: 'http://farm.example.test',
			Cookie: await connectBrowser(
				base,
				'http://farm.example.test',
				logs().match(/initial pairing code: (\d{6})/)[1]
			)
		});
		const remoteError = await remoteHost.json();
		assert.equal(remoteError.type, 'error');
		assert.equal(remoteError.status, 403);
		const inspected = await command('inspectInstallation', previous);
		assert.equal(inspected.status, 200, await inspected.clone().text());
		const summary = parse((await inspected.json()).result);
		assert.equal(summary.cameras, 1);
		assert.equal(summary.detectors, 1);
		const started = await command('importInstallation', {
			id: summary.id,
			keepRecordings: false,
			previousAppClosed: true
		});
		assert.equal(started.status, 200, await started.clone().text());
		for (let i = 0; i < 100; i++) {
			try {
				await readFile(path.join(directory, 'config.json'));
				break;
			} catch (error) {
				if (error.code !== 'ENOENT') throw error;
			}
			await delay(20);
		}
		const saved = JSON.parse(await readFile(path.join(directory, 'config.json'), 'utf8'));
		assert.deepEqual(saved.detectors[0].detection.source, ['rtsp://camera.example.test/live']);
		assert.ok(!('strategy' in saved.detectors[0].yolo));
		assert.match(await (await send(base + '/setup?step=cameras')).text(), /Imported barn/);
		assert.match(await (await send(base + '/setup?step=detectors')).text(), /Existing detector/);
		assert.equal(await readFile(path.join(previous, 'config.json'), 'utf8'), original);
		await assert.rejects(readFile(path.join(directory, 'starts.txt')), { code: 'ENOENT' });
	}
);

test(
	'production detector setup discovers the bundled preset files',
	{ timeout: 20000 },
	async (t) => {
		const { directory, base } = await startServer(t);
		await writeFile(
			path.join(directory, 'app.json'),
			JSON.stringify({ streams: [{ label: 'Barn', source: 'rtsp://camera.example.test/live' }] })
		);
		const response = await send(`${base}/setup?step=detectors`);
		assert.equal(response.status, 200);
		const html = await response.text();
		for (const name of ['Calving Catcher', 'Cow Catcher', 'General'])
			assert.ok(html.includes(name), `Bundled preset ${name} should be available`);
		assert.ok(html.includes('Choose a preset'));
		assert.ok(!html.includes('Cow mounting behaviour'));
	}
);

test(
	'pages follow each browser until the installation has a language of its own',
	{ timeout: 20000 },
	async (t) => {
		const { directory, base } = await startServer(t);
		const open = async (language) => {
			const response = await send(`${base}/setup?step=cameras`, {
				headers: language ? { 'Accept-Language': language } : {}
			});
			assert.equal(response.status, 200);
			return response.text();
		};
		const english = await open();
		assert.match(english, /<html lang="en"/);
		assert.match(english, /<title>Set up · AI Detector<\/title>/);
		const dutch = await open('nl-NL,nl;q=0.9,en;q=0.8');
		assert.match(dutch, /<html lang="nl"/);
		assert.match(dutch, /<title>Instellen · AI Detector<\/title>/);
		assert.doesNotMatch(dutch, /Connect your cameras/);
		// A language without a catalog is served in English rather than refused.
		assert.match(await open('pl-PL,pl;q=0.9'), /<html lang="en"/);

		// Messages raised on the server follow the request too, not only the pages.
		const refused = await send(`${base}/pair`, {
			method: 'POST',
			headers: {
				Host: 'barn.local',
				Origin: 'http://barn.local',
				Accept: 'text/html',
				'Accept-Language': 'de-DE,de;q=0.9',
				'Content-Type': 'application/x-www-form-urlencoded'
			},
			body: 'code=000000&name=Tablet'
		});
		assert.equal(refused.status, 400);
		const refusal = await refused.text();
		assert.match(refusal, /<html lang="de"/);
		assert.doesNotMatch(refusal, /The code did not match/);

		// Nothing was saved by looking; choosing a language is what records it.
		await assert.rejects(readFile(path.join(directory, 'app.json')), { code: 'ENOENT' });
		const chosen = await send(base + commands.setLanguage, {
			method: 'POST',
			headers: {
				Origin: base,
				'Content-Type': 'application/json',
				'x-sveltekit-pathname': '/setup',
				'x-sveltekit-search': '?step=cameras'
			},
			body: commandBody('fr')
		});
		assert.equal(chosen.status, 200, await chosen.clone().text());
		assert.equal(
			JSON.parse(await readFile(path.join(directory, 'app.json'), 'utf8')).language,
			'fr'
		);
		// From then on every browser sees the installation's language.
		assert.match(await open('nl-NL,nl;q=0.9'), /<html lang="fr"/);
		assert.match(await open(), /<html lang="fr"/);
	}
);

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
			await mkdir(path.join(directory, 'presets'));
			await writeFile(
				path.join(directory, 'presets', 'copy.json'),
				JSON.stringify({
					yolo: { model: 'safety.onnx', confidence: { helmet: 0.75 } },
					exporters: { disk: { directory: 'safety' } }
				})
			);
			const cameraInput = { label: 'Workshop camera', source, mode: 'view-only' };
			const host = deployment === 'LAN HTTP' ? 'barn.local:8080' : new URL(base).host;
			const origin = publicOrigin ?? `http://${host}`;
			const browserHeaders = { Host: host };
			if (deployment !== 'local HTTP') {
				const anonymous = await send(base + '/logs/output', { headers: browserHeaders });
				assert.equal(anonymous.status, 401);
				const code = logs().match(/initial pairing code: (\d{6})/)?.[1];
				assert.ok(code, logs());
				browserHeaders.Cookie = await connectBrowser(base, origin, code);
			}
			const firstVisit = await send(`${base}/setup`, { headers: browserHeaders });
			assert.equal(firstVisit.status, 302);
			assert.equal(
				new URL(firstVisit.headers.get('location'), base + '/setup').href,
				base + '/setup?step=cameras'
			);
			const page = await send(new URL(firstVisit.headers.get('location'), base + '/setup'), {
				headers: browserHeaders
			});
			assert.equal(page.status, 200);
			const html = await page.text();
			if (deployment === 'local HTTP') {
				assert.equal(firstVisit.headers.get('set-cookie'), null);
				assert.equal(page.headers.get('set-cookie'), null);
				await assert.rejects(readFile(path.join(directory, 'app.json')), { code: 'ENOENT' });
			}
			assert.ok(html.includes('<title>Set up · AI Detector</title>'));
			assert.ok(html.includes('Connect your cameras'));
			assert.ok(!html.includes('Calving Catcher'));
			const headers = {
				...browserHeaders,
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
			const detectorPage = await send(`${base}/setup?step=detectors`, {
				headers: browserHeaders
			});
			assert.equal(detectorPage.status, 200);
			const detectorHtml = await detectorPage.text();
			assert.ok(detectorHtml.includes('Copy'));
			assert.ok(!detectorHtml.includes('Calving Catcher'));
			const detectorSaved = await send(base + commands.saveDetector, {
				method: 'POST',
				headers,
				body: commandBody({
					meta: { label: 'Safety', preset: 'copy' },
					detector: {
						detection: { source: [source] },
						yolo: { model: 'safety.onnx', confidence: { helmet: 0.75 } },
						exporters: { disk: [{ directory: 'safety' }] }
					}
				})
			});
			assert.equal(detectorSaved.status, 200, await detectorSaved.clone().text());
			assert.equal((await detectorSaved.json()).type, 'result');

			const config = JSON.parse(await readFile(path.join(directory, 'config.json'), 'utf8'));
			assert.deepEqual(config.detectors[0].detection.source, [source]);
			assert.deepEqual(config.detectors[0].yolo, {
				model: 'safety.onnx',
				confidence: { helmet: 0.75 }
			});
			const app = JSON.parse(await readFile(path.join(directory, 'app.json'), 'utf8'));
			assert.equal(app.detectors[0].preset, 'copy');
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
			assert.match(
				await readFile(path.join(directory, 'logs/application.log'), 'utf8'),
				/Stop requested: SIGTERM/
			);
		}
	);
}

test(
	'production setup saves cameras before detectors and resumes incomplete setup',
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
		const unverified = await command('saveCamera', {
			label: 'Pen',
			source,
			mode: 'view-only'
		});
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
			mode: 'view-only',
			checkId: result.checkId
		});
		assert.equal(saved.type, 'result', JSON.stringify(saved));
		const id = parse(saved.result).id;
		assert.equal(parse(saved.result).monitored, false);
		assert.deepEqual(
			JSON.parse(await readFile(path.join(directory, 'config.json'), 'utf8')).detectors,
			[]
		);
		assert.equal((await send(base + '/')).headers.get('location'), '/setup');
		// The step stays in the address, so the first detector form opens without another redirect.
		assert.equal((await send(base + '/setup?step=detectors')).status, 200);
		assert.equal(
			(await send(base + '/setup?step=finish')).headers.get('location'),
			null,
			'Cameras without a detector can finish for live viewing'
		);
		assert.equal((await command('finishSetup')).type, 'result');
		assert.equal((await send(base + '/')).headers.get('location'), '/streams');
		const detectorSaved = await command('saveDetector', {
			meta: { label: 'Activity' },
			detector: {
				detection: { source: [result.source] },
				yolo: { model: 'yolo11n.pt' },
				exporters: { disk: [{}] }
			}
		});
		assert.equal(detectorSaved.type, 'result', JSON.stringify(detectorSaved));
		assert.equal((await send(base + '/')).headers.get('location'), '/detections');
		await assert.rejects(readFile(path.join(directory, 'starts.txt')), { code: 'ENOENT' });
		const renamed = await command('saveCamera', {
			id,
			label: 'Calving pen',
			source: result.source,
			mode: 'keep'
		});
		assert.equal(renamed.type, 'result', JSON.stringify(renamed));
		const other = await checkCamera(source + '-yard');
		assert.equal(
			(
				await command('saveCamera', {
					label: 'Yard',
					source: other.source,
					mode: 'view-only',
					checkId: other.checkId
				})
			).type,
			'result'
		);

		const yardDetector = await command('saveDetector', {
			meta: { label: 'Yard monitoring', preset: 'general' },
			detector: {
				detection: { source: [other.source] },
				yolo: { model: 'yolo11n.pt' },
				exporters: { disk: [{}] }
			}
		});
		assert.equal(yardDetector.type, 'result', JSON.stringify(yardDetector));
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

test(
	'a detector that follows a preset takes the new model of that preset when the server starts',
	{ skip: process.platform === 'win32', timeout: 20000 },
	async (t) => {
		const source = 'rtsp://camera.example.test/workshop';
		const { directory, base, logs } = await startServer(t, undefined, async (directory) => {
			await mkdir(path.join(directory, 'presets'));
			await Promise.all([
				// The preset as a new release brings it, with the second model.
				writeFile(
					path.join(directory, 'presets', 'workshop.json'),
					JSON.stringify({ detection: { interval: 2 }, yolo: { model: 'workshop-v2.onnx' } })
				),
				writeFile(
					path.join(directory, 'config.json'),
					JSON.stringify({
						detectors: [
							{
								detection: { source: [source], interval: 2 },
								yolo: { model: 'workshop-v1.onnx' },
								exporters: { disk: [{ directory: 'workshop' }] }
							}
						]
					})
				),
				writeFile(
					path.join(directory, 'app.json'),
					JSON.stringify({
						streams: [{ id: 'workshop-camera', label: 'Workshop camera', source }],
						detectors: [
							{
								label: 'Workshop rule',
								preset: 'workshop',
								// As recorded when the preset still gave the first model.
								presetVersion: presetVersion(
									'{"detection":{"interval":2},"yolo":{"model":"workshop-v1.onnx"}}'
								)
							}
						],
						telegrams: []
					})
				)
			]);
		});
		assert.equal((await send(`${base}/detectors`)).status, 200);
		const config = JSON.parse(await readFile(path.join(directory, 'config.json'), 'utf8'));
		assert.deepEqual(config.detectors, [
			{
				detection: { source: [source], interval: 2 },
				yolo: { model: 'workshop-v2.onnx' },
				exporters: { disk: [{ directory: 'workshop' }] }
			}
		]);
		const app = JSON.parse(await readFile(path.join(directory, 'app.json'), 'utf8'));
		assert.equal(app.detectors[0].preset, 'workshop');
		assert.match(logs(), /Detector "Workshop rule" now has the current settings of its preset/);
	}
);

test(
	'a detector that follows a published preset takes its new model once that can be downloaded',
	{ skip: process.platform === 'win32', timeout: 30000 },
	async (t) => {
		const source = 'rtsp://camera.example.test/workshop';
		let modelPublished = false;
		const github = createServer((request, response) => {
			const origin = `http://${request.headers.host}`;
			if (request.url === '/folder')
				return response.end(
					JSON.stringify([{ name: 'workshop.json', download_url: `${origin}/workshop.json` }])
				);
			if (request.url === '/workshop.json')
				return response.end(
					JSON.stringify({ detection: { interval: 2 }, yolo: { model: `${origin}/v2.pt` } })
				);
			response.statusCode = request.url === '/v2.pt' && modelPublished ? 200 : 404;
			response.end();
		});
		github.listen(0, '127.0.0.1');
		await once(github, 'listening');
		t.after(() => github.close());
		const published = `http://127.0.0.1:${github.address().port}`;
		const saved = {
			detection: { source: [source], interval: 2 },
			yolo: { model: 'workshop-v1.onnx' },
			exporters: { disk: [{ directory: 'workshop' }] }
		};
		const prepare = (directory) =>
			Promise.all([
				writeFile(path.join(directory, 'config.json'), JSON.stringify({ detectors: [saved] })),
				writeFile(
					path.join(directory, 'app.json'),
					JSON.stringify({
						streams: [{ id: 'workshop-camera', label: 'Workshop camera', source }],
						detectors: [
							{
								label: 'Workshop rule',
								preset: 'workshop',
								presetVersion: presetVersion(
									'{"detection":{"interval":2},"yolo":{"model":"workshop-v1.onnx"}}'
								)
							}
						],
						telegrams: []
					})
				)
			]);
		const detectors = async ({ directory, base }) => {
			assert.equal((await send(`${base}/detectors`)).status, 200);
			return JSON.parse(await readFile(path.join(directory, 'config.json'), 'utf8')).detectors;
		};

		// The preset names a model that is not there yet: the detector keeps what works.
		const early = await startServer(t, undefined, prepare, `${published}/folder`);
		assert.deepEqual(await detectors(early), [saved]);
		assert.match(early.logs(), /The model of preset "Workshop" cannot be downloaded now/);

		modelPublished = true;
		const later = await startServer(t, undefined, prepare, `${published}/folder`);
		assert.deepEqual(await detectors(later), [{ ...saved, yolo: { model: `${published}/v2.pt` } }]);
		assert.match(later.logs(), /Detector "Workshop rule" now has the current settings/);
	}
);

test(
	'production saved cameras remain editable when a preset file becomes invalid',
	{ skip: process.platform === 'win32', timeout: 20000 },
	async (t) => {
		const { directory, base } = await startServer(t);
		const source = 'rtsp://camera.example.test/workshop';
		const cameraId = 'workshop-camera';
		const detector = {
			detection: { source: [source], interval: 2 },
			yolo: { model: 'workshop-safety.onnx', confidence: { helmet: 0.75 } },
			exporters: { disk: [{ directory: 'workshop-recordings' }] }
		};
		const detectorMeta = {
			label: 'Workshop rule',
			preset: 'workshop',
			presetVersion: presetVersion(
				'{"detection":{"interval":2},"yolo":{"confidence":{"helmet":0.75},"model":"workshop-safety.onnx"}}'
			)
		};
		const configPath = path.join(directory, 'config.json');
		const configText = JSON.stringify({ detectors: [detector] });
		await mkdir(path.join(directory, 'presets'));
		const templatePath = path.join(directory, 'presets', 'workshop.json');
		await Promise.all([
			writeFile(configPath, configText),
			writeFile(
				path.join(directory, 'app.json'),
				JSON.stringify({
					streams: [{ id: cameraId, label: 'Workshop camera', source }],
					detectors: [detectorMeta],
					telegrams: []
				})
			),
			writeFile(templatePath, JSON.stringify(detector))
		]);
		const before = await send(`${base}/streams`);
		assert.equal(before.status, 200);
		assert.ok((await before.text()).includes('Workshop'));
		await writeFile(templatePath, '{"yolo":');
		for (const [route, savedValue, expectedContent] of [
			['/streams', 'Workshop camera', /Monitoring preset names are unavailable/],
			[`/streams/${cameraId}`, 'Workshop camera', /Camera name[\s\S]*Save changes/],
			[
				'/detectors/edit?label=Workshop%20rule',
				'workshop-safety.onnx',
				/Monitoring presets are unavailable/
			],
			['/detectors', 'Workshop rule', /Workshop camera/]
		]) {
			const response = await send(base + route);
			const html = await response.text();
			assert.equal(response.status, 200, `${route}: ${html}`);
			assert.match(html, expectedContent, route);
			assert.ok(html.includes(savedValue), `${route} must retain ${savedValue}`);
		}
		// A bookmark to a detector from the released web application opens its editor.
		for (const [oldPath, destination] of [
			['/detectors/add?label=Workshop%20rule', '/detectors/edit?label=Workshop%20rule'],
			['/detectors/add?label=Pen%20%26%20yard', '/detectors/edit?label=Pen%20%26%20yard']
		]) {
			const response = await send(base + oldPath);
			assert.equal(response.status, 302, oldPath);
			assert.equal(
				new URL(response.headers.get('location'), base + oldPath).href,
				base + destination
			);
		}
		for (const [route, title] of [
			['/streams/add', 'Add cameras'],
			['/detectors/add', 'Add a detector'],
			['/streams/missing', 'Camera not found'],
			['/detectors/edit?label=missing', 'Detector not found']
		]) {
			const response = await send(base + route);
			assert.equal(response.status, 200, route);
			assert.ok((await response.text()).includes(title), route);
		}
		const renamed = await send(base + commands.saveCamera, {
			method: 'POST',
			headers: {
				Origin: base,
				'Content-Type': 'application/json',
				'x-sveltekit-pathname': `/streams/${cameraId}`,
				'x-sveltekit-search': ''
			},
			body: commandBody({ id: cameraId, label: 'Main workshop', source, mode: 'keep' })
		});
		assert.equal(renamed.status, 200, await renamed.clone().text());
		const result = await renamed.json();
		assert.equal(result.type, 'result', JSON.stringify(result));
		assert.deepEqual(parse(result.result), { id: cameraId, monitored: true });
		assert.equal(await readFile(configPath, 'utf8'), configText);
		const app = JSON.parse(await readFile(path.join(directory, 'app.json'), 'utf8'));
		assert.deepEqual(app.streams, [{ id: cameraId, label: 'Main workshop', source }]);
		assert.deepEqual(app.detectors, [detectorMeta]);
		await assert.rejects(readFile(path.join(directory, 'starts.txt')), { code: 'ENOENT' });
	}
);

test('broken settings retain an accessible diagnostics download and explicit recovery flow', async (t) => {
	const { directory, base, logs } = await startServer(t);
	await writeFile(
		path.join(directory, 'config.json'),
		JSON.stringify({ detectors: [{ detection: { source: ['rtsp://camera.example.test/live'] } }] })
	);
	await writeFile(
		path.join(directory, 'app.json'),
		JSON.stringify({
			streams: [{ id: 'barn', label: 'Saved barn', source: 'rtsp://camera.example.test/live' }]
		})
	);
	const origin = 'http://barn.local';
	const headers = {
		Host: 'barn.local',
		Cookie: await connectBrowser(base, origin, logs().match(/initial pairing code: (\d{6})/)[1])
	};
	assert.equal((await send(base + '/setup?step=detectors')).status, 200);
	await writeFile(path.join(directory, 'config.json'), '{invalid settings');
	// Every page says which file is damaged and offers the same two ways forward.
	for (const route of ['/setup?step=cameras', '/streams', '/detectors', '/detections', '/status']) {
		const broken = await send(base + route, { headers });
		assert.equal(broken.status, 500, route);
		const page = await broken.text();
		assert.match(page, /config\.json is damaged and cannot be read/, route);
		assert.match(page, /Recover settings/, route);
		assert.match(page, /Download diagnostics/, route);
	}
	const download = await send(base + '/logs/diagnostics', { headers });
	assert.equal(download.status, 200);
	const files = unzipSync(new Uint8Array(await download.arrayBuffer()));
	assert.ok(files['system.json']);
	assert.match(Buffer.from(files['settings/config.json']).toString(), /unreadable/);
	assert.ok(
		!Object.keys(files).some((name) => name.includes('last-valid') || name.includes('devices'))
	);
	assert.equal(JSON.parse(Buffer.from(files['settings/app.json']).toString()).devices, undefined);
	assert.match(
		await (await send(base + '/recovery', { headers })).text(),
		/Restore saved settings/
	);
	const restored = await send(base + '/recovery', {
		method: 'POST',
		headers: {
			...headers,
			Origin: origin,
			Accept: 'text/html',
			'Content-Type': 'application/x-www-form-urlencoded'
		},
		body: ''
	});
	assert.equal(restored.status, 303, await restored.clone().text());
	assert.match(await (await send(base + '/setup?step=cameras', { headers })).text(), /Saved barn/);
	assert.equal(
		JSON.parse(await readFile(path.join(directory, 'config.json'), 'utf8')).detectors.length,
		1
	);
	await writeFile(path.join(directory, 'config.json.last-valid'), '{"key":"private-key",broken');
	const failedRecovery = await send(base + '/recovery', {
		method: 'POST',
		headers: {
			...headers,
			Origin: origin,
			Accept: 'text/html',
			'Content-Type': 'application/x-www-form-urlencoded'
		},
		body: ''
	});
	assert.equal(failedRecovery.status, 400);
	const support = unzipSync(
		new Uint8Array(await (await send(base + '/logs/diagnostics', { headers })).arrayBuffer())
	);
	const webLog = Buffer.from(support['logs/web.log']).toString();
	assert.match(webLog, /Could not restore the saved settings\nSyntaxError/);
	assert.ok(!webLog.includes('private-key'));
	assert.match(
		await (await send(base + '/logs/output', { headers })).text(),
		/Could not restore the saved settings/
	);
});

test('damaged app settings do not prevent server startup or local recovery', async (t) => {
	const saved = {
		config: { detectors: [] },
		app: { streams: [], detectors: [], telegrams: [], llms: [] }
	};
	const { base, logs } = await startServer(t, undefined, async (directory) => {
		await writeFile(path.join(directory, 'app.json'), '{broken');
		await writeFile(path.join(directory, 'config.json.last-valid'), JSON.stringify(saved));
	});
	assert.match(logs(), /Could not load connected devices from app.json/);
	assert.equal((await send(base + '/logs/diagnostics')).status, 200);
	const recovery = await send(base + '/recovery');
	assert.equal(recovery.status, 200);
	assert.match(await recovery.text(), /Restore saved settings/);
	const restored = await send(base + '/recovery', {
		method: 'POST',
		headers: {
			Origin: base,
			Accept: 'text/html',
			'Content-Type': 'application/x-www-form-urlencoded'
		},
		body: ''
	});
	assert.equal(restored.status, 303, await restored.clone().text());
	assert.equal((await send(base + '/devices')).status, 200);
});

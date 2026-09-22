import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { once } from 'node:events';
import { mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test, type TestContext } from 'node:test';
import { promisify } from 'node:util';
import ffmpeg from 'ffmpeg-static';
import onvif, { type DiscoveryProbeOptions, type ProbeCallback } from 'onvif';
import {
	cameraAddress,
	cameraStream,
	CameraConnectionError,
	connectionFailure
} from '../src/lib/server/cameras/connection.ts';
import {
	discoveredCameras,
	discoverCameras,
	resolveCameraStream
} from '../src/lib/server/cameras/discovery.ts';
import { CameraChecks } from '../src/lib/server/cameras/checks.ts';
import { fileMedia } from '../src/lib/server/file-media.ts';

const execute = promisify(execFile);

async function directory(t: TestContext) {
	const dir = await mkdtemp(path.join(tmpdir(), 'ai-camera-check-'));
	t.after(() => rm(dir, { recursive: true, force: true }));
	return dir;
}

async function server(
	t: TestContext,
	handler: (req: IncomingMessage, res: ServerResponse) => void
) {
	const instance = createServer(handler).listen(0, '127.0.0.1');
	await once(instance, 'listening');
	t.after(async () => {
		instance.closeAllConnections();
		await new Promise<void>((resolve, reject) =>
			instance.close((error) => (error ? reject(error) : resolve()))
		);
	});
	const address = instance.address();
	assert.ok(address && typeof address !== 'string');
	return `http://127.0.0.1:${address.port}`;
}

function soap(body: string) {
	return `<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body>${body}</s:Body></s:Envelope>`;
}

test('camera addresses accept separate credentials and never disclose them in errors', () => {
	assert.equal(cameraAddress('192.168.1.20').href, 'http://192.168.1.20/');
	const source = new URL(cameraStream('rtsp://camera/live', 'farm@home', 'private#/?'));
	assert.equal(decodeURIComponent(source.username), 'farm@home');
	assert.equal(decodeURIComponent(source.password), 'private#/?');
	assert.throws(() => cameraAddress('http://farm:secret@camera'), /separate fields/);
	assert.throws(() => cameraStream('file:///private'), /complete camera stream/);
	assert.match(
		connectionFailure(new Error('HTTP 401 at rtsp://farm:secret@camera')).message,
		/rejected the login/
	);
	assert.match(connectionFailure(new Error('ENOTFOUND camera')).message, /did not respond/);
	assert.match(connectionFailure(new Error('ENOSPC recording')).message, /not enough space/);
	assert.ok(
		!connectionFailure(new Error('rtsp://farm:secret@camera unknown failure')).message.includes(
			'secret'
		)
	);
});

test('discovery ignores malformed external replies, decodes names and deduplicates devices', () => {
	const reply = (XAddrs: string, scopes = '') => ({
		probeMatches: { probeMatch: { XAddrs, scopes } }
	});
	assert.deepEqual(
		discoveredCameras([
			reply(
				'file:///invalid http://192.168.1.20/onvif/device_service',
				'onvif://www.onvif.org/name/Calving%20pen'
			),
			reply('http://192.168.1.20/onvif/device_service', 'onvif://www.onvif.org/name/Calving%20pen'),
			reply('http://192.168.1.21/onvif/device_service'),
			{ malformed: true }
		]),
		[
			{ address: 'http://192.168.1.21/onvif/device_service', name: '192.168.1.21' },
			{ address: 'http://192.168.1.20/onvif/device_service', name: 'Calving pen' }
		]
	);
});

test('real ONVIF SOAP exchange resolves the selected NVR channel through the SDK', async (t) => {
	const requests: string[] = [];
	const address = await server(t, async (req, res) => {
		const chunks = [];
		for await (const chunk of req) chunks.push(chunk);
		const body = Buffer.concat(chunks).toString();
		requests.push(body);
		const responses: Record<string, string> = {
			GetSystemDateAndTime:
				'<GetSystemDateAndTimeResponse><SystemDateAndTime><DateTimeType>NTP</DateTimeType></SystemDateAndTime></GetSystemDateAndTimeResponse>',
			GetServices: `<GetServicesResponse><Service><Namespace>http://www.onvif.org/ver10/media/wsdl</Namespace><XAddr>${address}/media</XAddr></Service><Service><Namespace>http://www.onvif.org/ver10/device/wsdl</Namespace><XAddr>${address}/onvif/device_service</XAddr></Service></GetServicesResponse>`,
			GetProfiles:
				'<GetProfilesResponse><Profiles token="pen"><Name>Calving pen</Name></Profiles><Profiles token="yard"><Name>Yard</Name></Profiles></GetProfilesResponse>',
			GetStreamUri:
				'<GetStreamUriResponse><MediaUri><Uri>rtsp://camera/yard</Uri></MediaUri></GetStreamUriResponse>'
		};
		const operation = Object.keys(responses).find((name) => body.includes(`<${name}`));
		res.writeHead(operation ? 200 : 400, { 'Content-Type': 'application/soap+xml' });
		res.end(soap(operation ? responses[operation] : '<Fault/>'));
	});
	const result = await resolveCameraStream({
		address,
		username: 'farm',
		password: 'secret',
		streamUri: '',
		profileToken: 'yard'
	});
	assert.equal(result.source, 'rtsp://farm:secret@camera/yard');
	assert.deepEqual(result.connection, { address: `${address}/`, profileToken: 'yard' });
	assert.deepEqual(result.profiles, [
		{ token: 'pen', name: 'Calving pen' },
		{ token: 'yard', name: 'Yard' }
	]);
	assert.ok(requests.some((body) => body.includes('<ProfileToken>yard</ProfileToken>')));
	assert.ok(requests.some((body) => body.includes('<Username>farm</Username>')));
	await assert.rejects(
		resolveCameraStream({
			address,
			username: '',
			password: '',
			streamUri: '',
			profileToken: 'removed'
		}),
		/no longer available/
	);
});

test('ONVIF authentication failures are actionable without exposing raw device replies', async (t) => {
	const address = await server(t, (_req, res) => {
		res.writeHead(401, { 'Content-Type': 'application/soap+xml' });
		res.end(soap('<Fault><Reason><Text>NotAuthorized secret</Text></Reason></Fault>'));
	});
	await assert.rejects(
		resolveCameraStream({ address, username: 'farm', password: 'secret', streamUri: '' }),
		(error) => {
			assert.ok(error instanceof Error);
			assert.match(error.message, /rejected the login/);
			assert.ok(!error.message.includes('secret'));
			return true;
		}
	);
});

test(
	'an unavailable first NVR channel still exposes working channels before the recording check',
	{ timeout: 15000 },
	async (t) => {
		assert.ok(ffmpeg);
		const dir = await directory(t);
		const sample = path.join(dir, 'sample.mp4');
		await execute(ffmpeg, [
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
		const requests: string[] = [];
		const address = await server(t, async (req, res) => {
			if (req.method === 'GET') {
				if (req.url === '/yard') {
					res.writeHead(200, { 'Content-Type': 'video/mp4', 'Content-Length': bytes.length });
					res.end(bytes);
				} else {
					res.writeHead(503);
					res.end('Channel is offline');
				}
				return;
			}
			const chunks = [];
			for await (const chunk of req) chunks.push(chunk);
			const body = Buffer.concat(chunks).toString();
			requests.push(body);
			const responses: Record<string, string> = {
				GetSystemDateAndTime:
					'<GetSystemDateAndTimeResponse><SystemDateAndTime><DateTimeType>NTP</DateTimeType></SystemDateAndTime></GetSystemDateAndTimeResponse>',
				GetServices: `<GetServicesResponse><Service><Namespace>http://www.onvif.org/ver10/media/wsdl</Namespace><XAddr>${address}/media</XAddr></Service><Service><Namespace>http://www.onvif.org/ver10/device/wsdl</Namespace><XAddr>${address}/onvif/device_service</XAddr></Service></GetServicesResponse>`,
				GetProfiles:
					'<GetProfilesResponse><Profiles token="offline"><Name>Unused channel</Name></Profiles><Profiles token="yard"><Name>Yard</Name></Profiles></GetProfilesResponse>',
				GetStreamUri: `<GetStreamUriResponse><MediaUri><Uri>${address}/${body.includes('<ProfileToken>yard</ProfileToken>') ? 'yard' : 'offline'}</Uri></MediaUri></GetStreamUriResponse>`
			};
			const operation = Object.keys(responses).find((name) => body.includes(`<${name}`));
			res.writeHead(operation ? 200 : 400, { 'Content-Type': 'application/soap+xml' });
			res.end(soap(operation ? responses[operation] : '<Fault/>'));
		});
		const input = { address, username: '', password: '', streamUri: '' };
		const cache = new CameraChecks(path.join(dir, 'checks'));
		const first = await resolveCameraStream(input);
		assert.deepEqual(first.profiles, [
			{ token: 'offline', name: 'Unused channel' },
			{ token: 'yard', name: 'Yard' }
		]);
		const handshakeCount = requests.length;
		const resolvedFirst = await resolveCameraStream({ ...input, streamUri: first.source });
		await assert.rejects(cache.check(resolvedFirst.source, ffmpeg, []), CameraConnectionError);
		assert.equal(requests.length, handshakeCount, 'recording uses the resolved stream directly');
		assert.deepEqual(await readdir(path.join(dir, 'checks')), []);

		const selected = await resolveCameraStream({ ...input, profileToken: first.profiles[1].token });
		assert.equal(selected.source, `${address}/yard`);
		const selectedHandshakes = requests.length;
		const resolvedSelected = await resolveCameraStream({ ...input, streamUri: selected.source });
		const check = await cache.check(resolvedSelected.source, ffmpeg, []);
		cache.assert(check.checkId, selected.source);
		assert.equal(requests.length, selectedHandshakes);
		assert.ok(cache.file(check.checkId, 'picture.jpg'));
	}
);

test(
	'a real stream produces a playable setup recording and an opaque, expiring camera check',
	{ timeout: 15000 },
	async (t) => {
		assert.ok(ffmpeg, 'ffmpeg-static must provide the release platform binary');
		const dir = await directory(t);
		const sample = path.join(dir, 'sample.mp4');
		await execute(ffmpeg, [
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
		const address = await server(t, (_req, res) => {
			res.writeHead(200, { 'Content-Type': 'video/mp4', 'Content-Length': bytes.length });
			res.end(bytes);
		});
		let now = Date.now();
		const cache = new CameraChecks(path.join(dir, 'checks'), () => now);
		const result = await cache.check(`${address}/camera`, ffmpeg, []);
		cache.assert(result.checkId, result.source);
		assert.throws(() => cache.assert(result.checkId, 'rtsp://changed'), /camera address changed/);
		assert.ok(!result.previewUrl.includes(address));
		assert.equal(cache.file(result.checkId, '../sample.mp4'), null);
		const recording = cache.file(result.checkId, 'recording.mp4');
		const picture = cache.file(result.checkId, 'picture.jpg');
		assert.ok(recording && picture);
		await execute(ffmpeg, ['-v', 'error', '-i', recording, '-f', 'null', '-']);
		assert.equal((await readFile(picture)).subarray(0, 2).toString('hex'), 'ffd8');
		const range = await fileMedia(
			recording,
			new Request('http://localhost', { headers: { range: 'bytes=0-15' } }),
			'video/mp4'
		);
		assert.equal(range.status, 206);
		assert.equal((await range.arrayBuffer()).byteLength, 16);
		now += 15 * 60 * 1000;
		assert.throws(() => cache.assert(result.checkId, result.source), /expired/);
		assert.equal(cache.file(result.checkId, 'picture.jpg'), null);
		await cache.check(`${address}/camera`, ffmpeg, []);
		assert.deepEqual(
			(await readdir(path.join(dir, 'checks'))).filter((id) => id === result.checkId),
			[]
		);
	}
);

test(
	'failed or cancelled checks leave no partial recording and allow another attempt',
	{ timeout: 10000 },
	async (t) => {
		assert.ok(ffmpeg);
		const dir = await directory(t);
		const cache = new CameraChecks(dir);
		await assert.rejects(
			cache.check('http://127.0.0.1/invalid', path.join(dir, 'missing-ffmpeg'), []),
			/software is missing/
		);
		assert.deepEqual(await readdir(dir), []);
		const controller = new AbortController();
		let started!: () => void;
		const connected = new Promise<void>((resolve) => {
			started = resolve;
		});
		const address = await server(t, () => started());
		const pending = cache.check(address, ffmpeg, [], controller.signal);
		await connected;
		await assert.rejects(cache.check(address, ffmpeg, []), /still running/);
		controller.abort(new Error('Setup cancelled'));
		await assert.rejects(pending, /Setup cancelled/);
		assert.deepEqual(await readdir(dir), []);
		await assert.rejects(
			cache.check(address, path.join(dir, 'missing-ffmpeg'), []),
			/software is missing/
		);
	}
);

test('ONVIF scopes with XML attributes and malformed display names still expose the camera', () => {
	assert.deepEqual(
		discoveredCameras([
			{
				probeMatches: {
					probeMatch: {
						XAddrs: 'http://192.168.1.20',
						scopes: { _: 'onvif://www.onvif.org/name/Calving%20pen', $: { MatchBy: 'rfc3986' } }
					}
				}
			},
			{
				probeMatches: {
					probeMatch: {
						XAddrs: 'http://192.168.1.21',
						scopes: 'onvif://www.onvif.org/name/%broken'
					}
				}
			}
		]),
		[
			{ address: 'http://192.168.1.21/', name: '192.168.1.21' },
			{ address: 'http://192.168.1.20/', name: 'Calving pen' }
		]
	);
});

test('concurrent discovery shares one scan and releases the SDK error listener', async (t) => {
	const previous = onvif.Discovery.listenerCount('error');
	let finish!: ProbeCallback;
	const probe = t.mock.method(
		onvif.Discovery,
		'probe',
		(_options?: DiscoveryProbeOptions | ProbeCallback, callback?: ProbeCallback) => {
			assert.ok(callback);
			finish = callback;
		}
	);
	const first = discoverCameras();
	const second = discoverCameras();
	assert.equal(probe.mock.calls.length, 1);
	onvif.Discovery.emit('error', new Error('Local network access denied'));
	finish(new Error('Local network access denied'));
	finish(null, []);
	const [a, b] = await Promise.all([first, second]);
	assert.deepEqual(a, b);
	assert.ok(a.message);
	assert.match(a.message, /local network access/);
	assert.equal(onvif.Discovery.listenerCount('error'), previous);
});

test('a failed discovery start releases its listener and permits a new attempt', async (t) => {
	const previous = onvif.Discovery.listenerCount('error');
	const probe = t.mock.method(onvif.Discovery, 'probe', () => {
		throw new Error('Socket unavailable');
	});
	await assert.rejects(discoverCameras(), /Socket unavailable/);
	assert.equal(onvif.Discovery.listenerCount('error'), previous);
	probe.mock.mockImplementation(
		(_options?: DiscoveryProbeOptions | ProbeCallback, callback?: ProbeCallback) => {
			assert.ok(callback);
			callback(null, []);
		}
	);
	assert.deepEqual((await discoverCameras()).cameras, []);
});

test('invalid video is not diagnosed from timeout flags or credentials in the FFmpeg command', async (t) => {
	assert.ok(ffmpeg);
	const directoryPath = await directory(t);
	const camera = await server(t, (_req, res) =>
		res.end('This is a camera settings page, not a video stream.')
	);
	const url = new URL(camera);
	url.username = 'farmer';
	url.password = '401';
	const checks = new CameraChecks(directoryPath);
	await assert.rejects(
		checks.check(url.href, ffmpeg, []),
		/did not provide a supported video stream/
	);
	assert.deepEqual(await readdir(directoryPath), []);
});

test('unwritable test storage reports repair guidance and keeps the original failure', async (t) => {
	assert.ok(ffmpeg);
	const directoryPath = await directory(t);
	const occupied = path.join(directoryPath, 'occupied');
	await writeFile(occupied, 'An existing file must not be overwritten.');
	const checks = new CameraChecks(path.join(occupied, 'checks'));
	t.mock.method(console, 'warn', () => {});
	await assert.rejects(checks.check('rtsp://camera', ffmpeg, []), /data folder is writable/);
	assert.equal(await readFile(occupied, 'utf8'), 'An existing file must not be overwritten.');
});

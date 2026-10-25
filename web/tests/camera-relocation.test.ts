import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { RuntimeStatus } from '../src/lib/runtime.ts';
import type { Configuration } from '../src/lib/schema.ts';
import { movedSource } from '../src/lib/server/cameras/connection.ts';
import {
	macAddress,
	neighbourTable,
	onvifIdentity,
	type CameraMove
} from '../src/lib/server/cameras/identity.ts';
import { CameraRelocation, relocationNotices } from '../src/lib/server/cameras/relocation.ts';
import { cameraSetupStatus } from '../src/lib/server/configuration/camera-setup.ts';
import { sourceKey } from '../src/lib/server/source-key.ts';
import { addMonitoredCamera, settingsStore } from './support/configuration.ts';
import { server } from './support/http.ts';

const verifiedAt = '2026-10-23T12:00:00.000Z';

test('neighbour tables of Linux, macOS and Windows give each address its MAC address', () => {
	const linux = [
		'IP address       HW type     Flags       HW address            Mask     Device',
		'192.168.1.23     0x1         0x2         a4:14:37:0b:2c:9e     *        eth0',
		'192.168.1.40     0x1         0x0         00:00:00:00:00:00     *        eth0'
	].join('\n');
	const macos = [
		'? (192.168.1.23) at a4:14:37:b:2c:9e on en0 ifscope [ethernet]',
		'? (192.168.1.255) at ff:ff:ff:ff:ff:ff on en0 ifscope [ethernet]',
		'? (192.168.1.41) at (incomplete) on en0 ifscope [ethernet]'
	].join('\n');
	const windows = [
		'Interface: 192.168.1.5 --- 0xb',
		'  Internet Address      Physical Address      Type',
		'  192.168.1.23          a4-14-37-0b-2c-9e     dynamic',
		'  224.0.0.22            01-00-5e-00-00-16     static'
	].join('\r\n');
	const camera = ['192.168.1.23', 'a4:14:37:0b:2c:9e'];
	assert.deepEqual([...neighbourTable(linux)], [camera]);
	assert.deepEqual([...neighbourTable(macos)], [camera]);
	assert.deepEqual([...neighbourTable(windows)], [camera, ['224.0.0.22', '01:00:5e:00:00:16']]);
	assert.equal(macAddress('A4-14-37-0B-2C-9E'), 'a4:14:37:0b:2c:9e');
	assert.equal(macAddress('not a mac'), undefined);
});

test('a moved camera keeps its port, path and login', () => {
	assert.equal(
		movedSource('rtsp://farm:p%40ss@192.168.1.23:554/Streaming/101', '192.168.1.41'),
		'rtsp://farm:p%40ss@192.168.1.41:554/Streaming/101'
	);
	assert.equal(
		movedSource('http://192.168.1.23:8000/onvif/device_service', '192.168.1.41'),
		'http://192.168.1.41:8000/onvif/device_service'
	);
});

test('ONVIF identity keeps the serial number exactly as the camera writes it', async (t) => {
	const address = await server(t, async (req, res) => {
		const chunks = [];
		for await (const chunk of req) chunks.push(chunk);
		const body = Buffer.concat(chunks).toString();
		const replies: Record<string, string> = {
			GetSystemDateAndTime:
				'<tds:GetSystemDateAndTimeResponse><tds:SystemDateAndTime><tt:DateTimeType>NTP</tt:DateTimeType></tds:SystemDateAndTime></tds:GetSystemDateAndTimeResponse>',
			GetServices: `<tds:GetServicesResponse><tds:Service><tds:Namespace>http://www.onvif.org/ver10/media/wsdl</tds:Namespace><tds:XAddr>${address}/media</tds:XAddr></tds:Service><tds:Service><tds:Namespace>http://www.onvif.org/ver10/device/wsdl</tds:Namespace><tds:XAddr>${address}/onvif/device_service</tds:XAddr></tds:Service></tds:GetServicesResponse>`,
			GetDeviceInformation:
				'<tds:GetDeviceInformationResponse><tds:Manufacturer>Cam</tds:Manufacturer><tds:SerialNumber>00012345678901234567</tds:SerialNumber></tds:GetDeviceInformationResponse>',
			GetNetworkInterfaces:
				'<tds:GetNetworkInterfacesResponse><tds:NetworkInterfaces token="eth0"><tt:Info><tt:HwAddress>A4-14-37-0B-2C-9E</tt:HwAddress></tt:Info></tds:NetworkInterfaces></tds:GetNetworkInterfacesResponse>'
		};
		const operation = Object.keys(replies).find((name) => body.includes(`<${name}`));
		res.writeHead(operation ? 200 : 400, { 'Content-Type': 'application/soap+xml' });
		res.end(
			`<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:tds="http://www.onvif.org/ver10/device/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema"><s:Body>${operation ? replies[operation] : '<s:Fault/>'}</s:Body></s:Envelope>`
		);
	});
	assert.deepEqual(await onvifIdentity(`${address}/onvif/device_service`, 'farm', 'secret'), {
		serial: '00012345678901234567',
		mac: 'a4:14:37:0b:2c:9e'
	});
	assert.deepEqual(await onvifIdentity('http://127.0.0.1:9/onvif/device_service', '', ''), {});
});

test('relocating a camera moves its detectors, ONVIF address and finished setup along', async (t) => {
	const { store } = await settingsStore(t);
	const source = 'rtsp://farm:secret@192.168.1.23/live';
	const connection = { address: 'http://192.168.1.23/onvif/device_service', profileToken: 'main' };
	await addMonitoredCamera(store, { label: 'Pen', source, connection }, 'cow-catcher', verifiedAt);
	const camera = (await store.read()).app.streams[0];
	await store.rememberCameraDevice(camera.id, source, { mac: 'a4:14:37:0b:2c:9e' });
	const before = cameraSetupStatus(await store.read(), camera.id);

	const moves = await store.relocateCameras([
		{ id: camera.id, source, host: '192.168.1.41' },
		{ id: 'removed', source: 'rtsp://192.168.1.50/live', host: '192.168.1.51' }
	]);
	assert.deepEqual(moves, [{ id: camera.id, source, host: '192.168.1.41' }]);
	const saved = await store.read();
	const moved = 'rtsp://farm:secret@192.168.1.41/live';
	assert.equal(saved.app.streams[0].source, moved);
	assert.deepEqual(saved.app.streams[0].connection, {
		address: 'http://192.168.1.41/onvif/device_service',
		profileToken: 'main'
	});
	assert.deepEqual(saved.app.streams[0].device, { mac: 'a4:14:37:0b:2c:9e' });
	assert.deepEqual(saved.config.detectors[0].detection.source, [moved]);
	assert.deepEqual(cameraSetupStatus(saved, camera.id), before);

	// A camera someone changed meanwhile stays as they left it.
	assert.deepEqual(
		await store.relocateCameras([{ id: camera.id, source, host: '192.168.1.42' }]),
		[]
	);
	// Its identity belongs to the address it was learned at.
	await store.saveCamera({ id: camera.id, label: 'Pen', source: 'rtsp://192.168.1.60/live' });
	assert.equal((await store.read()).app.streams[0].device, undefined);
});

function settings(overrides: Partial<Configuration['app']> = {}): Configuration {
	const source = 'rtsp://192.168.1.23/live';
	return {
		config: {
			detectors: [
				{
					detection: { source: [source] },
					exporters: { telegram: [{ token: 'bot', chat: 'farm' }] }
				}
			]
		},
		app: {
			streams: [{ id: 'pen', label: 'Pen', source, device: { mac: 'a4:14:37:0b:2c:9e' } }],
			detectors: [{ label: 'Cows' }],
			telegrams: [],
			notifyCameraOutages: true,
			...overrides
		}
	} as unknown as Configuration;
}

function relocation(document: Configuration, state: string) {
	const sent: string[] = [];
	const located: string[][] = [];
	const learned: string[] = [];
	const status = () =>
		({
			cameras: document.app.streams.map((camera) => ({
				sourceKey: sourceKey(camera.source, '/data'),
				state
			}))
		}) as unknown as RuntimeStatus;
	const watch = new CameraRelocation({
		monitored: { monitoring: true, status },
		directory: '/data',
		settings: async () => document,
		remember: async () => undefined,
		relocate: async (moves: CameraMove[]) => moves,
		send: async (_recipient, text) => void sent.push(text),
		log: () => undefined,
		warn: (message, error) => assert.fail(`${message}: ${error}`),
		learn: async (camera) => {
			learned.push(camera.id!);
			return undefined;
		},
		locate: async (lost) => {
			located.push(lost.map((camera) => camera.id!));
			return lost.map((camera) => ({
				id: camera.id!,
				source: camera.source,
				host: '192.168.1.41'
			}));
		}
	});
	return { watch, sent, located, learned };
}

test('a camera without pictures for two minutes is looked for, at most every five minutes', async () => {
	const { watch, sent, located, learned } = relocation(settings(), 'offline');
	await watch.sample(0);
	await watch.sample(119000);
	assert.deepEqual(located, []);
	await watch.sample(120000);
	assert.deepEqual(located, [['pen']]);
	assert.equal(sent.length, 1);
	assert.match(sent[0], /Pen got a new network address \(192\.168\.1\.41\)/);
	assert.match(sent[0], /DHCP reservation/);
	await watch.sample(300000);
	assert.equal(located.length, 1);
	assert.deepEqual(learned, []);
});

test('a watched camera is asked once what tells it apart; a lost one without that is not searched', async () => {
	const unknown = settings({ streams: [{ id: 'pen', label: 'Pen', source: 'rtsp://x/live' }] });
	const watched = relocation(unknown, 'monitoring');
	await watched.watch.sample(0);
	await watched.watch.sample(10000);
	assert.deepEqual(watched.learned, ['pen']);
	const lost = relocation(unknown, 'offline');
	await lost.watch.sample(0);
	await lost.watch.sample(600000);
	assert.deepEqual(lost.located, []);
});

test('a camera that moved is told only to those who asked for outage notices', async () => {
	const { watch, sent, located } = relocation(settings({ notifyCameraOutages: false }), 'failed');
	await watch.sample(0);
	await watch.sample(120000);
	assert.equal(located.length, 1);
	assert.deepEqual(sent, []);
	assert.deepEqual(relocationNotices(settings(), []), []);
});

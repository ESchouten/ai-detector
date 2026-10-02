import assert from 'node:assert/strict';
import { test, type TestContext } from 'node:test';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { DeviceAccess, PairingError, localDashboard } from '../src/lib/server/device-access.ts';
import { ConfigurationStore } from '../src/lib/server/configuration/store.ts';
import { settingsRevision } from '../src/lib/server/configuration/advanced.ts';
import { writeJson } from '../src/lib/server/json-file.ts';

async function fixture(t: TestContext) {
	const directory = await mkdtemp(path.join(tmpdir(), 'detector-access-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	const files = {
		config: path.join(directory, 'config.json'),
		app: path.join(directory, 'app.json')
	};
	const store = new ConfigurationStore(files, () => {
		assert.fail('Pairing must not restart or reconfigure the detector');
	});
	return { files, store };
}

test('pairing is single-use; remembered browsers survive restart and can be revoked', async (t) => {
	const { files, store } = await fixture(t);
	const access = new DeviceAccess(store);
	const { code } = access.createPairing();
	const attempts = await Promise.allSettled([
		access.pair(code, 'Phone'),
		access.pair(code, 'Another phone')
	]);
	assert.equal(attempts.filter((result) => result.status === 'fulfilled').length, 1);
	const token = attempts.find((result) => result.status === 'fulfilled')!.value;
	assert.ok(!(await readFile(files.app, 'utf8')).includes(token));
	await assert.rejects(readFile(files.config), { code: 'ENOENT' });
	const reopened = new DeviceAccess(new ConfigurationStore(files));
	const device = await reopened.identify(token);
	assert.ok(device);
	assert.equal(device.name, 'Phone');
	assert.equal(await reopened.identify('invented'), undefined);
	await reopened.revoke(device.id);
	assert.equal(await reopened.identify(token), undefined);
	assert.equal(await access.identify(token), undefined);
});

test('pairing expires and wrong codes exhaust a bounded number of attempts', async (t) => {
	const { store } = await fixture(t);
	let now = 0;
	const access = new DeviceAccess(store, () => now);
	const expired = access.createPairing();
	now = expired.expires;
	await assert.rejects(access.pair(expired.code, 'Phone'), PairingError);
	const limited = access.createPairing();
	for (let attempt = 0; attempt < 10; attempt++)
		await assert.rejects(access.pair('incorrect', 'Phone'), PairingError);
	await assert.rejects(access.pair(limited.code, 'Phone'), /expired/);
	const fresh = access.createPairing();
	assert.ok(await access.identify(await access.pair(fresh.code, 'Phone')));
});

test('pairing and settings edits share a queue and do not overwrite each other', async (t) => {
	const { files } = await fixture(t);
	const store = new ConfigurationStore(files);
	await store.replace({ config: { detectors: [] }, app: {} });
	const revision = settingsRevision(await store.read());
	const access = new DeviceAccess(store);
	const pairing = access.createPairing();
	const [token] = await Promise.all([
		access.pair(pairing.code, 'Phone'),
		store.saveAdvanced('connections', [{ label: 'Validator', model: 'openai/vision' }], revision),
		store.saveCamera({ label: 'Barn', source: 'rtsp://camera.local/live', mode: 'view-only' })
	]);
	assert.ok(await access.identify(token));
	const saved = await store.read();
	assert.equal(saved.app.llms[0].label, 'Validator');
	assert.equal(saved.app.streams[0].label, 'Barn');
	assert.equal(saved.app.devices?.length, 1);
	await store.replace({ ...saved, app: { ...saved.app, devices: [] } });
	assert.ok(await access.identify(token));
});

test('device access remains usable with invalid detector settings and does not cache read failures', async (t) => {
	const { files, store } = await fixture(t);
	await writeFile(files.config, '{broken');
	await writeJson(files.app, { streams: 'invalid camera settings' });
	const access = new DeviceAccess(store);
	const token = await access.pair(access.createPairing().code, 'Phone');
	const app = await readFile(files.app, 'utf8');
	assert.ok(await access.identify(token));
	assert.equal(JSON.parse(app).streams, 'invalid camera settings');
	assert.equal(await readFile(files.config, 'utf8'), '{broken');
	await writeFile(files.app, '{broken');
	await assert.rejects(access.identify(token), SyntaxError);
	await writeFile(files.app, app);
	const device = await access.identify(token);
	assert.ok(device);
	await access.revoke(device.id);
	assert.equal(await access.identify(token), undefined);
});

test(
	'committed device access remains readable while a settings change waits for the runtime',
	{ timeout: 3000 },
	async (t) => {
		const { files } = await fixture(t);
		const applying = Promise.withResolvers<void>();
		const resume = Promise.withResolvers<void>();
		const store = new ConfigurationStore(files, () => ({
			validate: async () => {},
			apply: async () => {
				applying.resolve();
				await resume.promise;
			},
			stop: async () => {},
			fail: () => assert.fail('Runtime should succeed')
		}));
		const access = new DeviceAccess(store);
		const token = await access.pair(access.createPairing().code, 'Phone');
		const saving = store.replace({
			config: { detectors: [{ detection: { source: ['camera.mp4'] } }] },
			app: {}
		});
		await applying.promise;
		try {
			assert.equal((await access.identify(token))?.name, 'Phone');
		} finally {
			resume.resolve();
			await saving;
		}
	}
);

test('recovering settings preserves current access without reviving a revoked browser', async (t) => {
	const { files } = await fixture(t);
	const store = new ConfigurationStore(files);
	await store.replace({ config: { detectors: [] }, app: {} });
	const access = new DeviceAccess(store);
	const oldToken = await access.pair(access.createPairing().code, 'Old phone');
	await store.saveCamera({ label: 'Barn', source: 'rtsp://camera.local/live', mode: 'view-only' });
	const snapshot = JSON.parse(await readFile(`${files.config}.last-valid`, 'utf8'));
	assert.equal(snapshot.app.devices, undefined);
	await access.revoke((await access.identify(oldToken))!.id);
	const currentToken = await access.pair(access.createPairing().code, 'New phone');
	await writeFile(files.config, '{broken');
	await store.restore();
	assert.equal(await access.identify(oldToken), undefined);
	assert.ok(await access.identify(currentToken));
	await writeFile(files.app, '{broken');
	await store.restore();
	assert.equal((await store.read()).app.streams[0].label, 'Barn');
	assert.equal(await access.identify(currentToken), undefined);
});

test('local access requires both the actual loopback peer and a loopback host; forwarded headers grant nothing', () => {
	const url = new URL('http://127.0.0.1');
	assert.equal(localDashboard('127.0.0.1', url, new Request(url)), true);
	assert.equal(
		localDashboard(
			'192.168.1.9',
			url,
			new Request(url, { headers: { 'X-Forwarded-For': '127.0.0.1' } })
		),
		false
	);
	assert.equal(localDashboard('', url, new Request(url)), false);
	assert.equal(
		localDashboard('127.0.0.1', new URL('http://camera.example.test'), new Request(url)),
		false
	);
	assert.equal(
		localDashboard(
			'127.0.0.1',
			url,
			new Request(url, { headers: { Origin: 'https://other.example.test' } })
		),
		false
	);
	assert.equal(
		localDashboard(
			'127.0.0.1',
			url,
			new Request(url, { headers: { 'Sec-Fetch-Site': 'cross-site' } })
		),
		false
	);
});

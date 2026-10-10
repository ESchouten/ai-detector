import assert from 'node:assert/strict';
import { readdir } from 'node:fs/promises';
import path from 'node:path';
import { test } from 'node:test';
import { cameraSource, startServer } from './server.mjs';

async function camera(t, directory) {
	let connected;
	let disconnected;
	const started = new Promise((resolve) => {
		connected = resolve;
	});
	const closed = new Promise((resolve) => {
		disconnected = resolve;
	});
	const working = await cameraSource(t, directory, (request, response) => {
		if (request.url !== '/hanging') return false;
		response.once('close', disconnected);
		connected();
		return true;
	});
	return { working, hanging: new URL('/hanging', working).href, started, closed };
}

test(
	'production recording check cancellation stops FFmpeg after body consumption and permits immediate retry',
	{ timeout: 20000 },
	async (t) => {
		const app = await startServer(t);
		const source = await camera(t, app.directory);
		const controller = new AbortController();
		const check = (url, signal) =>
			fetch(`${app.base}/camera-checks`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json', Origin: app.base },
				body: JSON.stringify({ source: url }),
				signal
			});
		const pending = check(source.hanging, controller.signal);
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
		const retried = await check(source.working);
		assert.equal(retried.status, 200, await retried.clone().text());
		const result = await retried.json();
		assert.equal(result.source, source.working);
		assert.equal((await fetch(`${app.base}${result.previewUrl}`)).status, 200);
		assert.deepEqual(await readdir(path.join(app.directory, '.camera-checks')), [result.checkId]);
		assert.doesNotMatch(app.logs(), /AbortError|The operation was aborted|Internal Error/);
	}
);

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtemp, readFile, rm, stat, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { createHmac } from 'node:crypto';
import { fork } from 'node:child_process';
import { once } from 'node:events';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { DesktopInstance, CONTROL_PATH } from './desktop-instance.ts';

async function fixture(t: { after(fn: () => Promise<unknown> | void): void }) {
	const directory = await mkdtemp(path.join(tmpdir(), 'ai-instance-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	const instance = new DesktopInstance(directory);
	let quits = 0;
	let resolveQuit!: () => void;
	const quitRequested = new Promise<void>((resolve) => {
		resolveQuit = resolve;
	});
	const server = createServer(async (request, response) => {
		const result =
			instance.respond(
				new Request(`http://localhost${request.url}`, {
					method: request.method,
					headers: request.headers as Record<string, string>
				}),
				() => {
					quits++;
					resolveQuit();
				}
			) ?? new Response(null, { status: 404 });
		response.writeHead(result.status, Object.fromEntries(result.headers));
		response.end(await result.text());
	});
	await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
	t.after(
		() =>
			new Promise<void>((resolve, reject) =>
				server.close((error) => (error ? reject(error) : resolve()))
			)
	);
	const port = (server.address() as { port: number }).port;
	instance.publish(port);
	return { instance, port, directory, server, quitRequested, quits: () => quits };
}

test('a second launcher authenticates the existing dashboard without publishing another identity', async (t) => {
	const { instance, directory, port } = await fixture(t);
	const before = await readFile(path.join(directory, 'desktop-instance.json'), 'utf8');
	const second = new DesktopInstance(directory);
	assert.equal(await second.existing(port), true);
	assert.equal(await readFile(path.join(directory, 'desktop-instance.json'), 'utf8'), before);
	if (process.platform !== 'win32')
		assert.equal((await stat(path.join(directory, 'desktop-instance.json'))).mode & 0o777, 0o600);
	second.remove();
	assert.equal(await instance.existing(port), true);
});

test('unrelated services, redirects, stale and another user identity are never treated as the app', async (t) => {
	const { instance, directory, port } = await fixture(t);
	const token = path.join(directory, 'desktop-instance.json');
	await writeFile(token, JSON.stringify({ port, token: 'wrong-secret' }));
	assert.equal(await instance.existing(port, false, 100), false);
	assert.equal(await instance.existing(port + 1, false, 100), false);
	const server = createServer((_, response) => {
		response.writeHead(302, { location: 'https://example.com' });
		response.end();
	});
	await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
	t.after(() => new Promise<void>((resolve) => server.close(() => resolve())));
	const otherPort = (server.address() as { port: number }).port;
	await writeFile(token, JSON.stringify({ port: otherPort, token: 'wrong-secret' }));
	assert.equal(await instance.existing(otherPort, false, 100), false);
});

test('quit requires an authenticated request; probing alone never stops monitoring', async (t) => {
	const { instance, port, quits, quitRequested, directory } = await fixture(t);
	const forged = await fetch(`http://127.0.0.1:${port}${CONTROL_PATH}`, {
		method: 'POST',
		headers: {
			'X-AI-Detector-Challenge': 'a'.repeat(64),
			Authorization: 'forged'
		}
	});
	assert.equal(forged.status, 403);
	assert.equal(quits(), 0);
	assert.equal(await instance.existing(port), true);
	assert.equal(quits(), 0);
	const saved = JSON.parse(await readFile(path.join(directory, 'desktop-instance.json'), 'utf8'));
	const challenge = 'b'.repeat(64);
	const authorization = createHmac('sha256', saved.token)
		.update(`ai-detector-desktop/1:quit:${challenge}`)
		.digest('hex');
	const accepted = await fetch(`http://127.0.0.1:${port}${CONTROL_PATH}`, {
		method: 'POST',
		headers: { 'X-AI-Detector-Challenge': challenge, Authorization: authorization }
	});
	assert.equal(accepted.status, 200);
	await quitRequested;
	assert.equal(quits(), 1);
});

test('instance removal never deletes a replacement launcher identity', async (t) => {
	const { instance, port, directory } = await fixture(t);
	const replacement = new DesktopInstance(directory);
	replacement.publish(port);
	instance.remove();
	assert.ok(await readFile(path.join(directory, 'desktop-instance.json')));
	replacement.remove();
	await assert.rejects(readFile(path.join(directory, 'desktop-instance.json')), { code: 'ENOENT' });
});

test('a launch retries a stale identity while the new server publishes its record', async (t) => {
	const { instance, port, directory, server } = await fixture(t);
	await writeFile(
		path.join(directory, 'desktop-instance.json'),
		JSON.stringify({ port, token: 'previous-instance' })
	);
	server.prependOnceListener('request', () => instance.publish(port));
	assert.equal(await instance.existing(port, false, 1000), true);
});

test('quit waits until the owner finishes draining and exits, and already stopped is harmless', async (t) => {
	const directory = await mkdtemp(path.join(tmpdir(), 'ai-drain-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	const child = fork(new URL('./fixtures/desktop-server.ts', import.meta.url), {
		env: { ...process.env, TEST_DATA: directory },
		silent: true
	});
	t.after(() => {
		child.kill();
	});
	const [message] = await once(child, 'message');
	const instance = new DesktopInstance(directory);
	assert.equal(await instance.existing(message.port, true), true);
	assert.notEqual(child.exitCode, null, 'Acknowledging quit is not the same as finishing shutdown');
	assert.equal(await instance.existing(message.port, true), true);
});

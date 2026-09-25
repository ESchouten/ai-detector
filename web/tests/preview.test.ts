import assert from 'node:assert/strict';
import { test, type TestContext } from 'node:test';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout } from 'node:timers/promises';
import { parseMultipart } from '@remix-run/multipart-parser';
import { createPreviewStream } from '../src/lib/server/stream-preview.ts';
import { sanitizeTextForLogs } from '../src/lib/server/runtime-logs.ts';

const executable = fileURLToPath(new URL('./fixtures/preview.mjs', import.meta.url));
const posixOnly = { skip: process.platform === 'win32' };

function picture(chunk: Uint8Array | undefined): Uint8Array {
	assert.ok(chunk);
	const [part] = parseMultipart(Buffer.concat([chunk, Buffer.from('--frame--\r\n')]), {
		boundary: 'frame'
	});
	assert.equal(part.headers['content-type'], 'image/jpeg');
	assert.equal(Number(part.headers['content-length']), part.size);
	return part.bytes;
}

async function fixture(
	t: TestContext,
	settings: { ignoreTerm?: boolean; flood?: boolean; endOutput?: boolean } = {}
) {
	const directory = await mkdtemp(path.join(tmpdir(), 'detector-preview-'));
	const source = path.join(directory, 'source.json');
	await writeFile(source, JSON.stringify(settings));
	t.after(() => rm(directory, { recursive: true, force: true }));
	return { directory, source };
}

async function waitForExit(pid: number): Promise<void> {
	for (let i = 0; i < 150; i++) {
		try {
			process.kill(pid, 0);
		} catch {
			return;
		}
		await setTimeout(20);
	}
	assert.fail(`Preview process ${pid} did not exit`);
}

async function readStartedFile(file: string): Promise<string> {
	for (let i = 0; i < 100; i++) {
		try {
			return await readFile(file, 'utf8');
		} catch (error) {
			if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
		}
		await setTimeout(20);
	}
	assert.fail(`Preview did not create ${path.basename(file)}`);
}

for (const cancel of ['response', 'request'] as const) {
	test(`${cancel} cancellation kills a preview that ignores SIGTERM`, posixOnly, async (t) => {
		const { directory, source } = await fixture(t, { ignoreTerm: true });
		const abort = new AbortController();
		const reader = createPreviewStream(source, executable, abort.signal).getReader();
		t.after(() => reader.cancel());
		assert.equal(new TextDecoder().decode(picture((await reader.read()).value)), 'preview frame');
		const pid = Number(await readStartedFile(path.join(directory, 'pid')));
		if (cancel === 'response') await reader.cancel();
		else {
			abort.abort();
			assert.equal((await reader.read()).done, true);
			await waitForExit(pid);
		}
		assert.equal(await readFile(path.join(directory, 'terminated'), 'utf8'), 'SIGTERM');
		assert.throws(() => process.kill(pid, 0), { code: 'ESRCH' });
	});
}

test(
	'preview EOF closes the response and stops a producer that has not exited',
	posixOnly,
	async (t) => {
		const { directory, source } = await fixture(t, { endOutput: true });
		const abort = new AbortController();
		t.after(() => abort.abort());
		const reader = createPreviewStream(source, executable, abort.signal).getReader();
		assert.equal(new TextDecoder().decode(picture((await reader.read()).value)), 'preview frame');
		const pid = Number(await readStartedFile(path.join(directory, 'pid')));
		await assert.rejects(reader.read(), /Live stream ended/);
		await waitForExit(pid);
		assert.equal(await readFile(path.join(directory, 'terminated'), 'utf8'), 'SIGTERM');
	}
);

test(
	'a slow browser receives the latest whole picture without blocking camera capture',
	posixOnly,
	async (t) => {
		const { directory, source } = await fixture(t, { flood: true });
		const reader = createPreviewStream(
			source,
			executable,
			new AbortController().signal
		).getReader();
		t.after(() => reader.cancel());
		// More than the parser's default 1,000-part / 41 MiB upload limits:
		// an ongoing camera stream must not stop at an upload-oriented limit.
		assert.equal(await readStartedFile(path.join(directory, 'frames')), '1500');
		const { value, done } = await reader.read();
		assert.equal(done, false);
		const body = picture(value);
		assert.equal(body.byteLength, 64 * 1024);
		assert.ok(Number(new TextDecoder().decode(body.subarray(0, 4))) >= 1499);
		await reader.cancel();
	}
);

test('an already aborted preview never starts a process', posixOnly, async (t) => {
	const { directory, source } = await fixture(t);
	const reader = createPreviewStream(source, executable, AbortSignal.abort()).getReader();
	assert.equal((await reader.read()).done, true);
	await assert.rejects(readFile(path.join(directory, 'pid')), { code: 'ENOENT' });
});

test('runtime diagnostics redact both stream and HTTP credentials', () => {
	const text =
		'rtsp://farmer:secret@camera/live?api_key=private https://host/check?password=hidden';
	const safe = sanitizeTextForLogs(text);
	for (const credential of ['farmer', 'secret', 'private', 'hidden'])
		assert.ok(!safe.includes(credential));
	assert.ok(safe.includes('camera/live'));
});

test('runtime diagnostics redact partial URL parameters and non-HTTP source credentials', () => {
	const text =
		'Request failed: ?api_key=secret/with/slashes&quality=high ftp://farmer:password@host/file';
	const safe = sanitizeTextForLogs(text);
	for (const credential of ['secret', 'with/slashes', 'farmer', 'password'])
		assert.ok(!safe.includes(credential));
	assert.ok(safe.includes('quality=high'));
	assert.ok(safe.includes('host/file'));
});

test('a missing preview executable fails the response without an unhandled process error', async (t) => {
	const { source, directory } = await fixture(t);
	const warning = t.mock.method(console, 'warn', () => {});
	const reader = createPreviewStream(
		source,
		path.join(directory, 'missing-ffmpeg'),
		new AbortController().signal
	).getReader();
	await assert.rejects(reader.read(), /Live stream unavailable/);
	assert.ok(warning.mock.calls.length > 0);
});

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { diagnosticFiles } from '../src/lib/server/diagnostics.ts';
import { writeJson } from '../src/lib/server/json-file.ts';
import { DetectionArchive } from '../src/lib/server/archive.ts';
import { webLog } from '../src/lib/server/web-log.ts';

test('support bundles include rotated and TensorRT logs while redacting saved credentials and excluding recordings', async (t) => {
	const directory = await mkdtemp(path.join(tmpdir(), 'detector-diagnostics-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	await writeJson(path.join(directory, 'config.json'), {
		detectors: [
			{
				source: 'rtsp://farmer:camera-secret@192.168.1.2/feed',
				vlm: { key: 'vision-secret', headers: { Authorization: 'Bearer header-secret' } }
			}
		]
	});
	await writeJson(path.join(directory, 'app.json'), {
		telegrams: [{ token: 'telegram-secret' }],
		devices: [{ name: 'Private phone', hash: 'device-access-hash' }]
	});
	await mkdir(path.join(directory, 'logs'));
	await writeFile(
		path.join(directory, 'logs', 'detector.log.1'),
		'vision-secret telegram-secret Bearer header-secret rtsp://farmer:camera-secret@192.168.1.2/feed'
	);
	const build = path.join(directory, 'models', 'prepared', 'tensorrt', 'a'.repeat(64));
	await mkdir(build, { recursive: true });
	await writeFile(path.join(build, 'build.log'), 'Exporting model\nCompilation timeout\n');
	await writeFile(path.join(directory, 'logs', 'secret.json'), '{"private": true}');
	const files = [];
	for await (const file of diagnosticFiles(directory, { phase: 'running' })) files.push(file);
	assert.ok(files.some((file) => file.name === 'logs/detector.log.1'));
	assert.ok(
		files.some(
			(file) =>
				file.name.endsWith('/build.log') &&
				'content' in file &&
				file.content.includes('Compilation timeout')
		)
	);
	const text = JSON.stringify(files);
	for (const secret of [
		'vision-secret',
		'telegram-secret',
		'header-secret',
		'camera-secret',
		'device-access-hash',
		'Private phone',
		'secret.json'
	])
		assert.ok(!text.includes(secret), secret);
	assert.ok(text.includes('192.168.1.2'));
});

test('archive warnings and web failure details survive restart and reach the support bundle', async (t) => {
	const directory = await mkdtemp(path.join(tmpdir(), 'detector-web-log-'));
	t.after(async () => {
		await webLog.flush();
		await rm(directory, { recursive: true, force: true });
	});
	await webLog.initialize(directory);
	const archive = new DetectionArchive(path.join(directory, 'detections'));
	const damaged = path.join(archive.directory, 'activity', 'approved', '2026-01-01T12-00-00');
	await mkdir(damaged, { recursive: true });
	await writeFile(path.join(damaged, 'review.json'), '{"key":"private-validation-key",broken');
	assert.equal((await archive.page({ offset: 0, limit: 10 })).items.length, 0);
	webLog.error(
		'Could not restore the saved settings',
		Object.assign(new Error('private-validation-key'), { code: 'EACCES' })
	);
	await webLog.flush();
	await webLog.initialize(directory);
	await webLog.flush();
	const files = [];
	for await (const file of diagnosticFiles(directory, {})) files.push(file);
	const log = files.find((file) => file.name === 'logs/web.log');
	assert.ok(log && 'content' in log);
	assert.match(log.content, /Could not read recording activity\/approved/);
	assert.match(log.content, /SyntaxError/);
	assert.match(log.content, /Could not restore the saved settings[\s\S]*EACCES/);
	assert.ok(!log.content.includes('private-validation-key'));
});

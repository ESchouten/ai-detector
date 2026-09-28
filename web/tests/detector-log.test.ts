import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { DetectorLog, readLogTail } from '../src/lib/server/detector-log.ts';
import { searchLog } from '../src/lib/log-search.ts';

test('startup survives noisy inference, and the bounded redacted log survives reopening', async (t) => {
	const directory = await mkdtemp(path.join(tmpdir(), 'detector-log-'));
	const log = new DetectorLog(directory);
	t.after(async () => {
		await log.flush();
		await rm(directory, { recursive: true, force: true });
	});
	log.begin();
	log.append('\x1b[31mPreparing rtsp://farmer:secret@camera.local/live?token=hidden\x1b[0m\n');
	log.append('2026-09-28 20:00:00 INFO Predict time: 20ms\n'.repeat(10000));
	log.append('2026-09-28 20:01:00 ERROR Model failed\nTraceback:\n  model.py:20\nInvalid graph\n');
	const text = await log.read();
	assert.match(text, /Starting monitoring/);
	assert.match(text, /Preparing rtsp:/);
	assert.match(text, /Earlier activity omitted/);
	assert.match(text, /ERROR Model failed/);
	assert.doesNotMatch(text, /secret|hidden|farmer/);
	assert.ok(!text.includes(String.fromCharCode(27)));
	assert.ok(text.length < 132000);
	await log.flush();
	assert.equal(await readFile(path.join(directory, 'logs/application.log'), 'utf8'), text);
	assert.equal(await new DetectorLog(directory).read(), text);
	assert.equal(
		searchLog(text, 'INVALID GRAPH'),
		'2026-09-28 20:01:00 ERROR Model failed\nTraceback:\n  model.py:20\nInvalid graph\n'
	);
	log.begin();
	log.append('Configuration valid\n');
	await log.flush();
	assert.doesNotMatch(await new DetectorLog(directory).read(), /Model failed|omitted/);
});

test('search keeps multiline error details and is literal, case insensitive and optional', () => {
	const error =
		'2026-09-28T20:01:00 ERROR export failed\nTraceback:\n  model[0].py\nValidationError\n';
	const text = 'Configuration valid\n2026-09-28 20:00:00 INFO Downloading model\n' + error;
	assert.equal(searchLog(text, ' MODEL[0] '), error);
	assert.equal(searchLog(text, 'missing'), '');
	assert.equal(searchLog(text, ' '), text);
});

test('missing logs are empty, existing Python logs are bounded, and read failures stay visible', async (t) => {
	const directory = await mkdtemp(path.join(tmpdir(), 'detector-log-read-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	const file = path.join(directory, 'detector.log');
	assert.equal(await readLogTail(file), '');
	await writeFile(file, 'x'.repeat(600000) + '\nFinal error\n');
	const text = await readLogTail(file);
	assert.ok(text.length <= 512 * 1024);
	assert.ok(text.endsWith('Final error\n'));
	await assert.rejects(readLogTail(path.join(file, 'not-a-directory')));
});

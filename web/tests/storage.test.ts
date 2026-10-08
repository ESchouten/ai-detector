import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, readdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { DetectionArchive } from '../src/lib/server/archive.ts';
import { clearModelCache, recordingCleanup, removeRecordings } from '../src/lib/server/storage.ts';

test('recording cleanup requires an unchanged preview and preserves recent and unfinished events', async (t) => {
	const directory = await mkdtemp(path.join(tmpdir(), 'detector-cleanup-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	const archive = new DetectionArchive(directory);
	const old = 'activity/approved/2026-01-01T12-00-00';
	const recent = 'activity/rejected/2026-02-01T12-00-00';
	const pending = 'activity/.pending/2026-01-01T13-00-00';
	for (const item of [old, recent, pending]) {
		await mkdir(path.join(directory, item), { recursive: true });
		await writeFile(path.join(directory, item, 'image.jpg'), 'recording');
	}
	// Cleanup must still include damaged recordings, which the gallery cannot display.
	await writeFile(path.join(directory, old, 'metadata.json'), '{broken');
	const preview = await recordingCleanup(archive, '2026-02-01');
	assert.equal(preview.count, 1);
	const another = 'activity/rejected/2026-01-02T12-00-00';
	await mkdir(path.join(directory, another), { recursive: true });
	await assert.rejects(
		removeRecordings(archive, '2026-02-01', preview.revision),
		/recordings changed/
	);
	assert.equal(await readFile(path.join(directory, old, 'image.jpg'), 'utf8'), 'recording');
	const reviewed = await recordingCleanup(archive, '2026-02-01');
	assert.equal(await removeRecordings(archive, '2026-02-01', reviewed.revision), 2);
	for (const item of [old, another])
		await assert.rejects(readdir(path.join(directory, item)), { code: 'ENOENT' });
	for (const item of [recent, pending])
		assert.equal(await readFile(path.join(directory, item, 'image.jpg'), 'utf8'), 'recording');
});

test('model cleanup removes prepared and unused downloads while keeping referenced originals and custom models', async (t) => {
	const directory = await mkdtemp(path.join(tmpdir(), 'detector-model-cleanup-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	const url = 'https://models.example.test/detection.pt';
	const current = createHash('sha256').update(url).digest('hex').slice(0, 16);
	const unused = 'b'.repeat(16);
	for (const folder of [current, unused, 'prepared', 'custom']) {
		await mkdir(path.join(directory, 'models', folder), { recursive: true });
		await writeFile(path.join(directory, 'models', folder, 'model.pt'), 'weights');
	}
	await writeFile(path.join(directory, 'models', 'yolo.pt'), 'weights');
	await clearModelCache(directory, {
		detectors: [{ detection: { source: ['0'] }, yolo: { model: url } }]
	});
	assert.deepEqual(
		(await readdir(path.join(directory, 'models'))).sort(),
		[current, 'custom', 'yolo.pt'].sort()
	);
});

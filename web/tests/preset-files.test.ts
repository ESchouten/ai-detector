import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test, type TestContext } from 'node:test';
import { ConfigurationError } from '../src/lib/configuration.ts';
import {
	loadPresets,
	presetFile,
	readPresetChoices
} from '../src/lib/server/configuration/preset-files.ts';
import type { DetectorConfig } from '../src/lib/schema.ts';

async function fixture(t: TestContext) {
	const directory = await mkdtemp(path.join(tmpdir(), 'detector-presets-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	return directory;
}

test('preset files supply sorted IDs and readable names without a separate registration file', async (t) => {
	const directory = await fixture(t);
	for (const name of ['yard_monitoring', 'cow-catcher', 'calving-catcher'])
		await writeFile(
			path.join(directory, `${name}.json`),
			JSON.stringify({ yolo: { model: 'custom.pt' } })
		);
	await writeFile(path.join(directory, 'README.md'), 'Instructions');
	await mkdir(path.join(directory, 'nested.json'));
	await writeFile(path.join(directory, 'nested.json', 'ignored.json'), '{}');
	assert.deepEqual(await readPresetChoices(() => loadPresets(directory, {})), {
		presets: [
			{ id: 'calving-catcher', name: 'Calving Catcher' },
			{ id: 'cow-catcher', name: 'Cow Catcher' },
			{ id: 'yard_monitoring', name: 'Yard Monitoring' }
		]
	});
});

test('a preset’s modes are chosen with it and named like presets, and a mode file alone is a preset', async (t) => {
	const directory = await fixture(t);
	for (const name of [
		'calving-catcher',
		'calving-catcher.low-power',
		'calving-catcher.night_watch',
		'yard.low-power'
	])
		await writeFile(
			path.join(directory, `${name}.json`),
			JSON.stringify({ yolo: { model: 'custom.pt' } })
		);
	assert.deepEqual(await readPresetChoices(() => loadPresets(directory, {})), {
		presets: [
			{
				id: 'calving-catcher',
				name: 'Calving Catcher',
				modes: [
					{ id: 'low-power', name: 'Low Power' },
					{ id: 'night_watch', name: 'Night Watch' }
				]
			},
			{ id: 'yard.low-power', name: 'Yard Low Power' }
		]
	});
	assert.equal(presetFile('calving-catcher'), 'calving-catcher');
	assert.equal(presetFile('calving-catcher', 'low-power'), 'calving-catcher.low-power');
});

test('bundled preset files preserve their models, options and recording destinations', async () => {
	const directory = fileURLToPath(new URL('../../config/detector/', import.meta.url));
	const presets = await loadPresets(directory, {});
	assert.deepEqual(
		presets.map(({ id }) => id),
		[
			'calving-catcher-tailup',
			'calving-catcher',
			'calving-catcher.low-power',
			'cow-catcher',
			'general'
		]
	);
	for (const preset of presets) {
		const raw = JSON.parse(await readFile(path.join(directory, `${preset.id}.json`), 'utf8'));
		assert.deepEqual(preset.detector.yolo, raw.yolo);
		assert.deepEqual(preset.detector.exporters?.disk, [raw.exporters.disk]);
		assert.deepEqual(preset.telegram, raw.exporters.telegram);
		assert.deepEqual(preset.detector.detection, { ...raw.detection, source: [] });
	}
	assert.equal(
		presets.find(({ id }) => id === 'calving-catcher-tailup')!.detector.yolo?.model,
		presets.find(({ id }) => id === 'calving-catcher')!.detector.yolo?.model
	);
});

test('the low-power mode differs from its preset only in how often it looks and how much it needs to see', async () => {
	const presets = await loadPresets(
		fileURLToPath(new URL('../../config/detector/', import.meta.url)),
		{}
	);
	const modes = presets.flatMap((preset) => {
		const lowPower = presets.find(({ id }) => id === presetFile(preset.id, 'low-power'));
		if (lowPower) assert.deepEqual(lowPower.telegram, preset.telegram);
		return lowPower ? [[preset.detector, lowPower.detector]] : [];
	});
	assert.equal(modes.length, 1);
	// A newer model, another question, a changed threshold or Telegram setting must reach both.
	const shared = (detector: DetectorConfig) => ({
		...detector,
		detection: { ...detector.detection, interval: undefined },
		yolo: { ...detector.yolo, frames_min: undefined }
	});
	for (const [byDefault, lowPower] of modes) {
		assert.deepEqual(shared(lowPower), shared(byDefault));
		assert.ok(lowPower.detection.interval! > byDefault.detection.interval!);
	}
	const [[byDefault, lowPower]] = modes;
	assert.deepEqual([byDefault.detection.interval, byDefault.yolo?.frames_min], [1, 10]);
	assert.deepEqual([lowPower.detection.interval, lowPower.yolo?.frames_min], [5, 5]);
});

test('a preset’s Telegram object sets part of its alerts, never the recipient', async (t) => {
	const directory = await fixture(t);
	const file = path.join(directory, 'calving.json');
	const preset = (telegram: unknown) =>
		writeFile(
			file,
			JSON.stringify({ yolo: { model: 'custom.pt' }, exporters: { disk: {}, telegram } })
		);
	await preset({ include_video: false, alert_every: 3 });
	const [loaded] = await loadPresets(directory, {});
	assert.deepEqual(loaded.telegram, { include_video: false, alert_every: 3 });
	assert.deepEqual(loaded.detector.exporters, { disk: [{}] });
	for (const telegram of [
		{ token: 'fixture-token' },
		{ chat: '123' },
		{ quiet: { start: '22:00', end: '06:00' } },
		{ alert_every: 0 },
		{ unexpected: true },
		[{ include_video: false }]
	]) {
		await preset(telegram);
		await assert.rejects(
			loadPresets(directory, {}),
			(cause) => cause instanceof ConfigurationError && cause.message.includes(file)
		);
	}
});

test('adding, editing and removing local files changes the choices on the next read', async (t) => {
	const directory = await fixture(t);
	const file = path.join(directory, 'workshop-safety.json');
	const detector = {
		detection: { interval: 2, source: ['rtsp://template.test/replaced-by-camera'] },
		yolo: { model: 'custom-safety.onnx', confidence: { helmet: 0.73 }, cooldown: { helmet: 60 } },
		exporters: { disk: { directory: 'safety' }, webhook: { url: 'https://example.test/events' } }
	};
	await writeFile(file, JSON.stringify(detector));
	const original = await loadPresets(directory, {});
	assert.equal(original[0].name, 'Workshop Safety');
	assert.deepEqual(original[0].detector.yolo, detector.yolo);
	assert.deepEqual(original[0].detector.detection, { interval: 2, source: [] });
	assert.deepEqual(original[0].detector.exporters?.webhook, [detector.exporters.webhook]);
	await writeFile(file, JSON.stringify({ detection: { interval: 5 }, yolo: null }));
	await writeFile(
		path.join(directory, 'entry.json'),
		JSON.stringify({ yolo: { model: 'entry.pt' } })
	);
	const updated = await loadPresets(directory, {});
	assert.deepEqual(
		updated.map(({ id }) => id),
		['entry', 'workshop-safety']
	);
	assert.equal(updated[1].detector.yolo, null);
	assert.equal(updated[1].detector.detection.interval, 5);
	assert.deepEqual(original[0].detector.yolo, detector.yolo);
	await rm(file);
	assert.deepEqual(
		(await loadPresets(directory, {})).map(({ id }) => id),
		['entry']
	);
});

test('bundled files are used only when the optional local folder is absent', async (t) => {
	const directory = path.join(await fixture(t), 'presets');
	const bundled = {
		'config/detector/yard-watch.json': { yolo: { model: 'yard.pt' } },
		'config/detector/entry.json': { yolo: { model: 'entry.pt' } }
	};
	const before = structuredClone(bundled);
	const presets = await loadPresets(directory, bundled);
	assert.deepEqual(
		presets.map(({ id, name }) => ({ id, name })),
		[
			{ id: 'entry', name: 'Entry' },
			{ id: 'yard-watch', name: 'Yard Watch' }
		]
	);
	assert.deepEqual(bundled, before);
	await mkdir(directory);
	assert.deepEqual(await loadPresets(directory, bundled), []);
	await writeFile(
		path.join(directory, 'custom.json'),
		JSON.stringify({ yolo: { model: 'custom.pt' } })
	);
	assert.deepEqual(
		(await loadPresets(directory, bundled)).map(({ id }) => id),
		['custom']
	);
});

test('a file used as the preset folder is a configuration error', async (t) => {
	const file = path.join(await fixture(t), 'file.json');
	await writeFile(file, '{}');
	await assert.rejects(loadPresets(file, { 'general.json': {} }), /Could not read preset folder/);
});

test('invalid preset files identify the problem file and never fall back to another model', async (t) => {
	const directory = await fixture(t);
	const file = path.join(directory, 'workshop.json');
	for (const contents of [
		'{ incomplete',
		'null',
		'[]',
		'{"detection":[]}',
		'{"yolo":{"model":""}}',
		'{"yolo":{"model":"custom.pt","confidence":2}}',
		'{"unexpected":true}'
	]) {
		await writeFile(file, contents);
		const read = () => loadPresets(directory, { 'general.json': {} });
		const choices = await readPresetChoices(read);
		assert.deepEqual(choices.presets, []);
		assert.ok(choices.warning?.includes(file));
		await assert.rejects(
			read(),
			(cause) => cause instanceof ConfigurationError && cause.message === choices.warning
		);
	}
});

test('preset choices do not hide unexpected defects', async () => {
	const defect = new TypeError('Unexpected preset loader defect');
	await assert.rejects(
		readPresetChoices(async () => {
			throw defect;
		}),
		(cause) => cause === defect
	);
});

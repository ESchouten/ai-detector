import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test, type TestContext } from 'node:test';
import { ConfigurationError } from '../src/lib/configuration.ts';
import {
	loadPresetCatalog,
	readPresetChoices,
	resolvePresetCatalog
} from '../src/lib/server/configuration/preset-catalog.ts';

const entry = {
	id: 'workshop',
	name: 'Workshop safety',
	description: 'Watch the work area.',
	guidance: 'Keep the entrance visible.',
	configuration: 'models/workshop.json'
};

async function fixture(t: TestContext) {
	const directory = await mkdtemp(path.join(tmpdir(), 'detector-presets-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	await mkdir(path.join(directory, 'models'));
	const file = path.join(directory, 'presets.json');
	await writeFile(file, JSON.stringify({ defaultPreset: entry.id, presets: [entry] }));
	return { directory, file, configuration: path.join(directory, entry.configuration) };
}

test('optional preset choices preserve display information without exposing detector settings', async (t) => {
	const { file, configuration } = await fixture(t);
	await writeFile(configuration, JSON.stringify({ yolo: { model: 'custom.pt' } }));
	assert.deepEqual(await readPresetChoices(() => loadPresetCatalog(file)), {
		catalogue: {
			defaultPreset: entry.id,
			presets: [
				{ id: entry.id, name: entry.name, description: entry.description, guidance: entry.guidance }
			]
		}
	});
});

test('optional preset choices return invalid-template guidance without changing strict catalogue reads', async (t) => {
	const { file, configuration } = await fixture(t);
	for (const contents of ['{ incomplete', '{"yolo":{"model":""}}']) {
		await writeFile(configuration, contents);
		const choices = await readPresetChoices(() => loadPresetCatalog(file));
		assert.deepEqual(choices.catalogue, { presets: [] });
		assert.ok(choices.warning);
		await assert.rejects(loadPresetCatalog(file), { message: choices.warning });
	}
	await rm(configuration);
	const missing = await readPresetChoices(() => loadPresetCatalog(file));
	assert.deepEqual(missing.catalogue, { presets: [] });
	assert.match(missing.warning!, /Could not read preset file/);
});

test('optional preset choices do not hide unexpected defects', async () => {
	const defect = new TypeError('Unexpected catalogue defect');
	await assert.rejects(
		readPresetChoices(async () => {
			throw defect;
		}),
		(cause) => cause === defect
	);
});

test('bundled preset data preserves existing models and exposes a configured generic default', async () => {
	const file = fileURLToPath(new URL('../../config/presets.json', import.meta.url));
	const catalog = await loadPresetCatalog(file);
	assert.equal(catalog.defaultPreset, 'general');
	for (const [id, name] of [
		['calving', 'calving-catcher'],
		['mounts', 'cow-catcher'],
		['general', 'general']
	]) {
		const raw = JSON.parse(
			await readFile(new URL(`../../config/detector/${name}.json`, import.meta.url), 'utf8')
		);
		const preset = catalog.presets.find((item) => item.id === id)!;
		assert.deepEqual(preset.detector.yolo, raw.yolo);
		assert.deepEqual(preset.detector.exporters?.disk, [raw.exporters.disk]);
		assert.deepEqual(preset.detector.detection, { ...raw.detection, source: [] });
	}
});

test('a local catalogue loads arbitrary models, classes, guidance and exporters relative to its file', async (t) => {
	const { file, configuration } = await fixture(t);
	const detector = {
		detection: { interval: 2 },
		yolo: { model: 'custom-safety.onnx', confidence: { helmet: 0.73 }, cooldown: { helmet: 60 } },
		exporters: { disk: { directory: 'safety' }, webhook: { url: 'https://example.test/events' } }
	};
	await writeFile(configuration, JSON.stringify(detector));
	const catalog = await loadPresetCatalog(file);
	assert.equal(catalog.presets[0].guidance, entry.guidance);
	assert.deepEqual(catalog.presets[0].detector.yolo, detector.yolo);
	assert.deepEqual(catalog.presets[0].detector.detection, { interval: 2, source: [] });
	assert.deepEqual(catalog.presets[0].detector.exporters?.webhook, [detector.exporters.webhook]);
	await writeFile(
		configuration,
		JSON.stringify({ detection: { interval: 5 }, yolo: null, exporters: { disk: {} } })
	);
	const updated = await loadPresetCatalog(file);
	assert.equal(updated.presets[0].detector.yolo, null);
	assert.equal(updated.presets[0].detector.detection.interval, 5);
	assert.deepEqual(catalog.presets[0].detector.yolo, detector.yolo);
});

test('catalogue IDs are independent of application actions and defaults are optional', async () => {
	const ids = ['keep', 'copy', 'view-only'];
	const catalog = await resolvePresetCatalog(
		{ presets: ids.map((id) => ({ ...entry, id })) },
		async () => ({})
	);
	assert.equal(catalog.defaultPreset, undefined);
	assert.deepEqual(
		catalog.presets.map(({ id }) => id),
		ids
	);
	assert.deepEqual(
		await resolvePresetCatalog({ presets: [] }, async () => assert.fail('No file expected')),
		{ presets: [] }
	);
});

test('malformed, ambiguous or invalid catalogue entries fail instead of choosing another model', async () => {
	for (const input of [
		null,
		{ presets: [{ ...entry, id: ' ' }] },
		{ presets: [entry, entry] },
		{ defaultPreset: 'missing', presets: [entry] },
		{ presets: [{ ...entry, typo: true }] }
	])
		await assert.rejects(
			resolvePresetCatalog(input, async () => ({})),
			ConfigurationError
		);
	await assert.rejects(
		resolvePresetCatalog({ presets: [entry] }, async () => ({
			yolo: { model: 'custom.pt', confidence: 2 }
		})),
		ConfigurationError
	);
	await assert.rejects(
		resolvePresetCatalog({ presets: [entry] }, async () => ({ unexpected: true })),
		ConfigurationError
	);
});

test('missing and invalid referenced files remain errors, including an explicit missing catalogue', async (t) => {
	const { directory, file, configuration } = await fixture(t);
	await assert.rejects(loadPresetCatalog(file), /Could not read preset file/);
	await writeFile(configuration, '{ incomplete');
	await assert.rejects(loadPresetCatalog(file), /not valid JSON/);
	await writeFile(file, 'null');
	await assert.rejects(loadPresetCatalog(file), /Invalid preset catalogue/);
	await assert.rejects(
		loadPresetCatalog(path.join(directory, 'missing.json')),
		/Could not read preset file/
	);
});

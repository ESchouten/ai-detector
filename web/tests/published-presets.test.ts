import assert from 'node:assert/strict';
import { test, type TestContext } from 'node:test';
import {
	modelAvailable,
	publishedPresets,
	withPublished
} from '../src/lib/server/configuration/published-presets.ts';

const folder = 'https://presets.example.test/folder';
const signal = () => AbortSignal.timeout(5000);

/** A stand-in for the published folder: answers by address, and notes what was asked for. */
function publish(t: TestContext, replies: Record<string, unknown>) {
	const asked: { url: string; headers: Record<string, string> }[] = [];
	t.mock.method(globalThis, 'fetch', async (url: string, init: RequestInit) => {
		asked.push({ url, headers: init.headers as Record<string, string> });
		if (!(url in replies)) return new Response('Not found', { status: 404 });
		return replies[url] instanceof Response ? replies[url] : Response.json(replies[url]);
	});
	return asked;
}

test('published presets come from a folder listing, without what this version cannot use', async (t) => {
	t.mock.method(console, 'warn', () => undefined);
	const asked = publish(t, {
		[folder]: [
			{ name: 'cow-catcher.json', download_url: `${folder}/cow-catcher.json` },
			{ name: 'from-a-later-version.json', download_url: `${folder}/later.json` },
			{ name: 'README.md', download_url: `${folder}/README.md` },
			{ name: 'archive', download_url: null }
		],
		[`${folder}/cow-catcher.json`]: {
			yolo: { model: 'https://models.example.test/cowcatcherV18.pt', confidence: 0.9 },
			exporters: { disk: { directory: 'mounts' } }
		},
		[`${folder}/later.json`]: { yolo: { model: 'next.pt', an_option_of_tomorrow: true } }
	});
	const presets = await publishedPresets(folder, signal());
	assert.deepEqual(
		presets.map(({ id, name, detector }) => ({ id, name, model: detector.yolo?.model })),
		[
			{
				id: 'cow-catcher',
				name: 'Cow Catcher',
				model: 'https://models.example.test/cowcatcherV18.pt'
			}
		]
	);
	assert.deepEqual(presets[0].detector.detection.source, []);
	assert.deepEqual(
		asked.map(({ url }) => url),
		[folder, `${folder}/cow-catcher.json`, `${folder}/later.json`]
	);
});

test('a folder that cannot be read is an error, so that nothing is changed on a guess', async (t) => {
	publish(t, { [`${folder}/empty`]: { message: 'API rate limit exceeded' } });
	await assert.rejects(publishedPresets(folder, signal()), /answered 404/);
	await assert.rejects(publishedPresets(`${folder}/empty`, signal()));
});

test('a published preset replaces the bundled one of the same name, and the others stay', () => {
	const preset = (id: string, model: string) => ({
		id,
		name: id,
		detector: { detection: { source: [] }, yolo: { model } }
	});
	assert.deepEqual(
		withPublished(
			[preset('cow-catcher', 'bundled.pt'), preset('general', 'yolo11n.pt')],
			[preset('cow-catcher', 'published.pt'), preset('calving-catcher', 'new.pt')]
		).map(({ id, detector }) => [id, detector.yolo?.model]),
		[
			['calving-catcher', 'new.pt'],
			['cow-catcher', 'published.pt'],
			['general', 'yolo11n.pt']
		]
	);
});

test('a model counts as available only when its address answers; a bare name is not checked', async (t) => {
	const model = 'https://models.example.test/cowcatcherV18.pt';
	const asked = publish(t, { [model]: new Response('weights') });
	const detector = (name: string) => ({ detection: { source: [] }, yolo: { model: name } });
	assert.equal(await modelAvailable(detector(model), signal()), true);
	assert.equal(asked[0].headers.Range, 'bytes=0-0');
	assert.equal(
		await modelAvailable(detector('https://models.example.test/gone.pt'), signal()),
		false
	);
	t.mock.method(globalThis, 'fetch', async () => {
		throw new TypeError('fetch failed');
	});
	assert.equal(await modelAvailable(detector(model), signal()), false);
	assert.equal(await modelAvailable(detector('yolo11n.pt'), signal()), true);
});

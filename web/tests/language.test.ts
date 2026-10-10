import assert from 'node:assert/strict';
import { test, type TestContext } from 'node:test';
import { readFile, readdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import {
	LANGUAGE_NAMES,
	LOCALES,
	language,
	negotiateLocale,
	type Locale
} from '../src/lib/locales.ts';
import { ConfigurationStore } from '../src/lib/server/configuration/store.ts';
import {
	currentLanguage,
	installationLanguage,
	loadInstallationLanguage,
	rememberInstallationLanguage,
	requestedLanguage,
	runInLanguage
} from '../src/lib/server/request-language.ts';
import { settingsStore } from './support/configuration.ts';

const catalogs = path.join(import.meta.dirname, '../src/locales');

interface Entry {
	msgid: string;
	plural?: string;
	translations: string[];
}

/** The catalogs as Wuchale writes them: entries separated by blank lines, strings JSON-quoted. */
async function readCatalog(locale: string): Promise<{ header: string; entries: Entry[] }> {
	const [header, ...blocks] = (await readFile(path.join(catalogs, `${locale}.po`), 'utf8'))
		.replaceAll('\r\n', '\n')
		.trim()
		.split('\n\n');
	const entries = blocks.map((block) => {
		const fields: Record<string, string> = {};
		let field = '';
		for (const line of block.split('\n')) {
			if (line.startsWith('#')) continue;
			const start = /^(msgctxt|msgid_plural|msgid|msgstr(?:\[\d+\])?) (.*)$/.exec(line);
			if (start) field = start[1];
			fields[field] = (fields[field] ?? '') + JSON.parse(start ? start[2] : line);
		}
		return {
			msgid: fields.msgid,
			plural: fields.msgid_plural,
			translations: Object.keys(fields)
				.filter((name) => name.startsWith('msgstr'))
				.sort()
				.map((name) => fields[name])
		};
	});
	return { header, entries };
}

const placeholders = (text: string) => (text.match(/\{\d+\}|<\/?\d+\/?>/g) ?? []).sort();

async function fixture(t: TestContext, requested?: Locale) {
	const saved: (Locale | undefined)[] = [];
	const { files, store } = await settingsStore(t, undefined, {
		requested: () => requested,
		saved: (value) => saved.push(value)
	});
	const stored = async () => JSON.parse(await readFile(files.app, 'utf8')).language;
	return { files, store, saved, stored };
}

const camera = { label: 'Barn', source: 'rtsp://camera.example.test/live' };

test('a browser gets the first of its languages that the interface has', () => {
	assert.equal(negotiateLocale('nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7'), 'nl');
	assert.equal(negotiateLocale('fr-CH, fr;q=0.9, en;q=0.8, de;q=0.7, *;q=0.5'), 'fr');
	// Quality decides, not position; a language switched off with q=0 is never chosen.
	assert.equal(negotiateLocale('pl,de-AT;q=0.8,en;q=0.9'), 'en');
	assert.equal(negotiateLocale('en;q=0, de'), 'de');
	// Nothing we can serve leaves the choice to the caller, which falls back to English.
	for (const header of ['es-ES,es;q=0.9', '*', '', null, undefined])
		assert.equal(negotiateLocale(header), undefined);
});

test('every language has a catalog, its own name, and nothing left untranslated', async () => {
	const files = (await readdir(catalogs)).filter((name) => name.endsWith('.po')).sort();
	assert.deepEqual(files, LOCALES.map((locale) => `${locale}.po`).sort());
	const source = await readCatalog('en');
	assert.ok(source.entries.length > 500);
	for (const locale of LOCALES) {
		assert.ok(LANGUAGE_NAMES[locale]);
		const { header, entries } = await readCatalog(locale);
		const forms = Number(/nplurals=(\d+)/.exec(header)?.[1]);
		assert.deepEqual(
			entries.map((entry) => entry.msgid),
			source.entries.map((entry) => entry.msgid),
			`${locale}.po does not list the same messages as en.po; run pnpm i18n`
		);
		for (const entry of entries) {
			const where = `${locale}.po: ${JSON.stringify(entry.msgid)}`;
			assert.equal(entry.translations.length, entry.plural ? forms : 1, where);
			for (const translation of entry.translations) {
				assert.ok(translation.trim(), `${where} is not translated`);
				// Placeholders may move, never change. A singular may spell its number out.
				if (!entry.plural)
					assert.deepEqual(placeholders(translation), placeholders(entry.msgid), where);
			}
		}
	}
});

test('messages thrown to the person using the application are translated too', async () => {
	// Wuchale skips `throw` statements unless wuchale.config.js keeps teaching it otherwise.
	const { entries } = await readCatalog('en');
	const messages = new Set(entries.map((entry) => entry.msgid));
	assert.ok(messages.has('A detector with this name already exists.'));
	assert.ok(messages.has('Choose a preset for this detector.'));
	// Log lines, header names and text the code itself matches on stay out of the catalogs.
	for (const technical of ['No space left on device', 'Content-Type', 'ArrowLeft', 'Not found'])
		assert.ok(!messages.has(technical), technical);
});

test('text follows the request being answered, and the installation outside any request', async (t) => {
	t.after(() => rememberInstallationLanguage(undefined));
	rememberInstallationLanguage(undefined);
	assert.equal(currentLanguage(), 'en');
	assert.equal(language(), 'en');
	rememberInstallationLanguage('de');
	// A detector that stops by itself, or a reply in Telegram, belongs to no request.
	assert.equal(currentLanguage(), 'de');
	await runInLanguage({ language: 'nl', requested: 'fr' }, async () => {
		await new Promise((resolve) => setTimeout(resolve, 1));
		assert.equal(currentLanguage(), 'nl');
		assert.equal(requestedLanguage(), 'fr');
	});
	assert.equal(requestedLanguage(), undefined);
	assert.equal(currentLanguage(), 'de');
});

test('an installation takes the language of the browser that sets it up, then keeps it', async (t) => {
	const dutch = await fixture(t, 'nl');
	// Opening the application writes nothing.
	await dutch.store.read();
	await assert.rejects(readFile(dutch.files.app), { code: 'ENOENT' });
	await dutch.store.saveCamera(camera);
	assert.equal(await dutch.stored(), 'nl');
	assert.equal(dutch.saved.at(-1), 'nl');

	// A later visitor with another language changes settings, not the language.
	const french = new ConfigurationStore(dutch.files, undefined, {
		requested: () => 'fr',
		saved: () => undefined
	});
	await french.saveCamera({
		label: 'Stable',
		source: 'rtsp://stable.example.test/live'
	});
	assert.equal(await dutch.stored(), 'nl');

	await french.saveLanguage('de');
	assert.equal(await dutch.stored(), 'de');
	assert.equal((await french.read()).app.streams.length, 2);
});

test('settings saved without a browser language stay as they were', async (t) => {
	const { store, files, stored } = await fixture(t);
	await store.saveCamera(camera);
	assert.equal(await stored(), undefined);
	assert.ok(!('language' in JSON.parse(await readFile(files.app, 'utf8'))));
});

test('a language this version does not have leaves the other settings readable', async (t) => {
	const { store, files, saved } = await fixture(t);
	await writeFile(files.app, JSON.stringify({ language: 'tlh', streams: [camera] }));
	const { app } = await store.read();
	assert.equal(app.language, undefined);
	assert.equal(app.streams[0].label, 'Barn');
	assert.equal(saved.at(-1), undefined);

	t.after(() => rememberInstallationLanguage(undefined));
	await loadInstallationLanguage(files.app);
	assert.equal(installationLanguage(), undefined);
	await writeFile(files.app, JSON.stringify({ language: 'fr' }));
	await loadInstallationLanguage(files.app);
	assert.equal(installationLanguage(), 'fr');
	// Damaged settings are reported where they are edited; text falls back to each browser.
	await writeFile(files.app, '{');
	await loadInstallationLanguage(files.app);
	assert.equal(installationLanguage(), undefined);
});

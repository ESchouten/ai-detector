import { AsyncLocalStorage } from 'node:async_hooks';
import { isLocale, SOURCE_LOCALE, type Locale } from '../locales.ts';
import { readJson } from './json-file.ts';

interface RequestLanguage {
	language: Locale;
	/** The supported language the browser asked for, when it stated one. */
	requested?: Locale;
}

const request = new AsyncLocalStorage<RequestLanguage>();
let installation: Locale | undefined;

/** Answer one request in its language; everything it awaits sees the same language. */
export function runInLanguage<T>(language: RequestLanguage, work: () => T): T {
	return request.run(language, work);
}

/**
 * The language to write text in right now: that of the request being answered, or for work
 * no request started (the detector stopping by itself, a Telegram reply) the installation's own.
 */
export function currentLanguage(): Locale {
	return request.getStore()?.language ?? installation ?? SOURCE_LOCALE;
}

/** What the browser being answered asked for, so the first saved settings can keep it. */
export function requestedLanguage(): Locale | undefined {
	return request.getStore()?.requested;
}

/** The language saved in app.json, once someone has set up the application or chosen one. */
export function installationLanguage(): Locale | undefined {
	return installation;
}

export function rememberInstallationLanguage(language: Locale | undefined): void {
	installation = language;
}

/** Read the saved language when the server starts, before any settings are opened. */
export async function loadInstallationLanguage(appFile: string): Promise<void> {
	// Unreadable settings are reported where they are edited; text falls back to each browser.
	const app = await readJson<{ language?: unknown }>(appFile).catch(() => null);
	installation = isLocale(app?.language) ? app.language : undefined;
}

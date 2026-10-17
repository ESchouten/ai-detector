import toRuntime from 'wuchale/runtime';
import { LOCALES } from '../lib/locales.ts';
import { currentLanguage } from '../lib/server/request-language.ts';

/**
 * Catalogs for server code. Every language is loaded when the server starts; each use picks
 * the language of the request being answered, so text written outside a request (a detector
 * that stops by itself, a reply in Telegram) is never empty: it uses the installation's language.
 *
 * @param {(loadID: number, locale: string) => import('wuchale/runtime').CatalogModule} loadCatalog
 * @param {number} loadCount
 */
export function serverRuntimes(loadCatalog, loadCount) {
	const runtimes = Object.fromEntries(
		LOCALES.map((locale) => [
			locale,
			Array.from({ length: loadCount }, (_, loadID) =>
				toRuntime(loadCatalog(loadID, locale), locale)
			)
		])
	);
	return (loadID = 0) => runtimes[currentLanguage()][loadID];
}

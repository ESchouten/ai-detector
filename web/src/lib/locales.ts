/** Interface languages, the source language first. Each has a catalog in src/locales. */
export const LOCALES = ['en', 'nl', 'de', 'fr'] as const;
export type Locale = (typeof LOCALES)[number];
export const SOURCE_LOCALE: Locale = 'en';

/** Each language under its own name, so it can be found by someone who reads no other. */
export const LANGUAGE_NAMES: Record<Locale, string> = {
	en: 'English',
	nl: 'Nederlands',
	de: 'Deutsch',
	fr: 'Français'
};

export function isLocale(value: unknown): value is Locale {
	return LOCALES.includes(value as Locale);
}

/**
 * The best supported language for a browser's Accept-Language header, or nothing when the
 * browser states no preference we can serve. Regional variants match their language: nl-BE is nl.
 */
export function negotiateLocale(header: string | null | undefined): Locale | undefined {
	const preferences = (header ?? '')
		.split(',')
		.map((entry, index) => {
			const [tag, ...parameters] = entry.trim().split(';');
			const quality = parameters.find((parameter) => parameter.trim().startsWith('q='));
			const weight = quality === undefined ? 1 : Number(quality.trim().slice(2));
			return { language: tag.trim().toLowerCase().split('-')[0], weight, index };
		})
		.filter(({ language, weight }) => language && weight > 0)
		.sort((a, b) => b.weight - a.weight || a.index - b.index);
	return preferences.map(({ language }) => language).find(isLocale);
}

/**
 * The language the interface is shown in, for formatting dates and numbers to match it.
 * Call it without an argument: the build passes the language of the catalog in use.
 */
export function language(locale: string = SOURCE_LOCALE): string {
	return locale;
}

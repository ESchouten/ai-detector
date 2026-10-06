import { language } from './locales.ts';

const formats = new Map<string, Intl.DateTimeFormat>();

/** Dates and times follow the interface language, not the browser's, so a page reads as one. */
function dateFormat(locale: string, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
	const key = `${locale}:${JSON.stringify(options)}`;
	let format = formats.get(key);
	if (!format) formats.set(key, (format = new Intl.DateTimeFormat(locale, options)));
	return format;
}

function parse(value: string | number | Date): Date | null {
	const date = value instanceof Date ? value : new Date(value);
	return Number.isNaN(date.getTime()) ? null : date;
}

/** 21:12 or 9:12 PM, as the interface language writes it. */
export function timeOfDay(value: string | number | Date): string {
	const date = parse(value);
	return date ? dateFormat(language(), { timeStyle: 'short' }).format(date) : String(value);
}

export function clockTime(value: string | number | Date): string {
	const date = parse(value);
	return date ? dateFormat(language(), { timeStyle: 'medium' }).format(date) : String(value);
}

/** 3 October 2026. A day written as 2026-10-03 is that day here, not midnight in UTC. */
export function calendarDate(value: string | number | Date): string {
	const day = typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value);
	const date = parse(day ? `${value}T00:00:00` : value);
	return date ? dateFormat(language(), { dateStyle: 'long' }).format(date) : String(value);
}

/** Tue 6: a day on a time axis that spans a week. */
export function weekday(value: string | number | Date): string {
	const date = parse(value);
	return date
		? dateFormat(language(), { weekday: 'short', day: 'numeric' }).format(date)
		: String(value);
}

function calendarDay(date: Date): string {
	return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

/** Recordings are grouped by the calendar day in their name; recent days read as words. */
export function dayHeading(day: string, now = new Date()): string {
	const date = parse(`${day}T00:00:00`);
	if (!date) return day;
	if (day === calendarDay(now)) return 'Today';
	const yesterday = new Date(now);
	yesterday.setDate(now.getDate() - 1);
	if (day === calendarDay(yesterday)) return 'Yesterday';
	return dateFormat(
		language(),
		date.getFullYear() === now.getFullYear()
			? { weekday: 'long', month: 'long', day: 'numeric' }
			: { dateStyle: 'full' }
	).format(date);
}

/** Clip length as a player shows it: 0:09, 1:42. */
export function clipLength(seconds: number): string {
	const total = Math.max(0, Math.round(seconds));
	return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

export function gigabytes(bytes: number): string {
	const digits = bytes < 10 * 1024 ** 3 ? 1 : 0;
	const amount = new Intl.NumberFormat(language(), {
		minimumFractionDigits: digits,
		maximumFractionDigits: digits
	}).format(bytes / 1024 ** 3);
	// The unit is translated: French writes Go.
	return /* @wc-include */ `${amount} GB`;
}

export function percent(fraction: number): string {
	return `${Math.round(fraction * 100)}%`;
}

const PLURAL_CATEGORIES: Intl.LDMLPluralRule[] = ['zero', 'one', 'two', 'few', 'many', 'other'];
const pluralRules = new Map<string, (count: number) => number>();

/** Which of a language's plural forms a count takes; forms are listed in the order above. */
function pluralForm(locale: string): (count: number) => number {
	let form = pluralRules.get(locale);
	if (!form) {
		const rules = new Intl.PluralRules(locale);
		const used = new Set(rules.resolvedOptions().pluralCategories);
		const order = PLURAL_CATEGORIES.filter((category) => used.has(category));
		pluralRules.set(locale, (form = (count) => order.indexOf(rules.select(count))));
	}
	return form;
}

/**
 * Text that depends on a count: `plural(2, ['# camera', '# cameras'])` is "2 cameras".
 * Write the English singular and plural; `#` becomes the number. The build substitutes the
 * forms of the interface language (which may have more than two) and passes that language.
 */
export function plural(count: number, forms: string[], locale = 'en'): string {
	const form = forms[pluralForm(locale)(count)] ?? forms[forms.length - 1];
	return form.replace('#', new Intl.NumberFormat(locale).format(count));
}

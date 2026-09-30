import { type LlmConnection, type DetectorConfig, type VLMConfig } from './schema.ts';

export const GEMINI_MODEL = 'gemini/gemini-3.1-flash-lite';
export const AI_STUDIO_KEYS = 'https://aistudio.google.com/apikey';

/** Apply credentials in one place; detector questions and fallbacks remain local. */
export function assignConnection<T extends DetectorConfig>(
	detector: T,
	connection: LlmConnection,
	preset?: DetectorConfig
): Omit<T, 'vlm'> & { vlm: VLMConfig[] } {
	const [first, ...fallbacks] = detector.vlm ?? [];
	const settings = first ?? preset?.vlm?.[0] ?? { prompt: '', strategy: 'IMAGE' };
	return {
		...detector,
		vlm: [
			{
				...settings,
				enabled: true,
				model: connection.model,
				key: connection.key ?? null,
				url: connection.url ?? null,
				headers: connection.headers ?? {}
			},
			...fallbacks
		]
	};
}

export function connectionMatches(settings: VLMConfig, connection: LlmConnection): boolean {
	const models = Array.isArray(settings.model) ? settings.model : [settings.model];
	const headers = settings.headers ?? {};
	const expected = connection.headers ?? {};
	return (
		settings.enabled !== false &&
		models.length === 1 &&
		models[0] === connection.model &&
		(settings.key ?? null) === (connection.key ?? null) &&
		(settings.url ?? null) === (connection.url ?? null) &&
		Object.keys(headers).length === Object.keys(expected).length &&
		Object.entries(headers).every(([name, value]) => expected[name] === value)
	);
}

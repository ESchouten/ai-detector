import { type LlmConnection, type DetectorConfig, type VLMConfig } from './schema.ts';

export const GEMINI_MODELS = [
	'gemini/gemini-3.8-flash',
	'gemini/gemini-3.7-flash',
	'gemini/gemini-3.6-flash',
	'gemini/gemini-3.5-flash',
	'gemini/gemini-3.5-flash-lite',
	'gemini/gemini-3.1-flash-lite'
];
export const AI_STUDIO_KEYS = 'https://aistudio.google.com/apikey';

/** A preset question without credentials or model choices is waiting for its first connection. */
export function awaitsConnection(detector: DetectorConfig): boolean {
	const settings = detector.vlm?.[0];
	return Boolean(settings?.prompt.trim() && settings.key == null && !settings.model?.length);
}

export function suggestedConnection(
	detector: DetectorConfig,
	connections: LlmConnection[]
): LlmConnection | undefined {
	const available = connections.filter((connection) => connection.key != null);
	return awaitsConnection(detector) && available.length === 1 ? available[0] : undefined;
}

/** Apply credentials in one place; detector questions and fallbacks remain local. */
export function assignConnection<T extends DetectorConfig>(
	detector: T,
	connection: LlmConnection,
	preset?: DetectorConfig
): Omit<T, 'vlm'> & { vlm: VLMConfig[] } {
	const [first, ...fallbacks] = detector.vlm ?? [];
	const settings = first ?? preset?.vlm?.[0] ?? { prompt: '', strategy: 'VIDEO' };
	return {
		...detector,
		vlm: [
			{
				...settings,
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
	const expectedModels = Array.isArray(connection.model) ? connection.model : [connection.model];
	const headers = settings.headers ?? {};
	const expected = connection.headers ?? {};
	return (
		settings.key != null &&
		models.length === expectedModels.length &&
		models.every((model, index) => model === expectedModels[index]) &&
		(settings.key ?? null) === (connection.key ?? null) &&
		(settings.url ?? null) === (connection.url ?? null) &&
		Object.keys(headers).length === Object.keys(expected).length &&
		Object.entries(headers).every(([name, value]) => expected[name] === value)
	);
}

/** Disconnect every verification step; its question and model remain editable. */
export function clearVerificationKeys(detector: DetectorConfig): DetectorConfig {
	return {
		...detector,
		vlm: detector.vlm?.map((settings) => ({ ...settings, key: null }))
	};
}

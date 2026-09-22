import * as v from 'valibot';
import { DEFAULT_SCHEMA_URL } from '../../schema.ts';
import { configurationSchema } from '../../configuration.ts';

const editorSchema = v.looseObject({
	$defs: v.looseObject({ DetectorConfig: v.record(v.string(), v.unknown()) })
});

export async function getEditorSchema(schemaUrl?: string | null) {
	if (!schemaUrl || schemaUrl === DEFAULT_SCHEMA_URL) return configurationSchema;
	try {
		const response = await fetch(schemaUrl, { signal: AbortSignal.timeout(10000) });
		if (!response.ok) return configurationSchema;
		return v.parse(editorSchema, await response.json());
	} catch {
		return configurationSchema;
	}
}

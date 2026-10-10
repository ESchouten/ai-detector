import Ajv from 'ajv';
import { configurationSchema, webConfigurationSchema } from './configuration.ts';

export type SettingsDocument = 'config' | 'connections';

const { model, key, url, headers } = configurationSchema.$defs.VLMConfig.properties;
export const settingsSchemas: Record<SettingsDocument, Record<string, unknown>> = {
	config: webConfigurationSchema,
	connections: {
		type: 'array',
		title: 'Shared AI connections',
		items: {
			type: 'object',
			additionalProperties: false,
			required: ['label', 'model'],
			properties: {
				label: {
					type: 'string',
					minLength: 1,
					description:
						'Unique connection name. Unassign a connection before removing or renaming it here.'
				},
				model: {
					title: model.title,
					anyOf: [model.anyOf[0], { ...model.anyOf[1], minItems: 1 }]
				},
				key,
				url,
				headers
			}
		}
	}
};

const ajv = new Ajv({ strict: false, allErrors: true });
const validators = Object.fromEntries(
	Object.entries(settingsSchemas).map(([name, schema]) => [name, ajv.compile(schema)])
);

/** Use the same bundled schemas in the editor and at the save boundary. */
export function parseSettings(document: SettingsDocument, text: string): unknown {
	const value: unknown = JSON.parse(text);
	const validate = validators[document];
	if (!validate(value)) {
		throw new Error(
			validate
				.errors!.map((issue) => {
					const detail =
						issue.keyword === 'additionalProperties'
							? `has unsupported property ${JSON.stringify(issue.params.additionalProperty)}`
							: issue.message;
					return `${issue.instancePath || '/'} ${detail}`;
				})
				.join('\n')
		);
	}
	return value;
}

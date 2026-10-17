import {
	ajv,
	configurationSchema,
	issueMessage,
	validateConfig,
	webConfigurationSchema
} from './configuration.ts';

export const SETTINGS_DOCUMENTS = ['config', 'connections'] as const;
export type SettingsDocument = (typeof SETTINGS_DOCUMENTS)[number];

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

const validators = {
	config: validateConfig,
	connections: ajv.compile(settingsSchemas.connections)
};

/** What the editor checks before it offers to save; the store checks every save itself. */
export function parseSettings(document: SettingsDocument, text: string): unknown {
	const value: unknown = JSON.parse(text);
	const validate = validators[document];
	if (!validate(value))
		throw new Error(
			validate
				.errors!.map((issue) => `${issue.instancePath || '/'} ${issueMessage(issue)}`)
				.join('\n')
		);
	return value;
}

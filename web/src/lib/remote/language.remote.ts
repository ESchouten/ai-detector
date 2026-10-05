import { command } from '$app/server';
import * as v from 'valibot';
import { LOCALES } from '$lib/locales';
import { configuration } from '$lib/server/configuration';
import { configurationAction } from '$lib/server/configuration/request';

/** The language of this installation: every device, and the replies sent to Telegram. */
export const setLanguage = command(v.picklist(LOCALES), (language) =>
	configurationAction(configuration.saveLanguage(language))
);

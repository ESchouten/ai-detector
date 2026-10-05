import path from 'node:path';
import { APP_CONFIG_PATH, CONFIG_PATH, DATA_DIRECTORY } from '../application-paths.ts';
import { managedDetector } from '../detector-service.ts';
import { rememberInstallationLanguage, requestedLanguage } from '../request-language.ts';
import { ConfigurationStore } from './store.ts';

export const configuration = new ConfigurationStore(
	{ config: CONFIG_PATH, app: APP_CONFIG_PATH, runtime: path.join(DATA_DIRECTORY, 'runtime.json') },
	managedDetector,
	{ requested: requestedLanguage, saved: rememberInstallationLanguage }
);

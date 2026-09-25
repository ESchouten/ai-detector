import { APP_CONFIG_PATH, CONFIG_PATH } from '../application-paths.ts';
import { managedDetector } from '../detector-service.ts';
import { ConfigurationStore } from './store.ts';
import { readPresets } from './presets.ts';

export const configuration = new ConfigurationStore(
	{ config: CONFIG_PATH, app: APP_CONFIG_PATH },
	readPresets,
	managedDetector
);

import { DATA_DIRECTORY } from '../application-paths.ts';
import { configuration } from '../configuration/index.ts';
import { InstallationImport } from './service.ts';

export const installationImport = new InstallationImport(DATA_DIRECTORY, configuration);

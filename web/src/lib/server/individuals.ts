import path from 'node:path';
import { DATA_DIRECTORY } from './application-paths.ts';
import { IndividualsFolder } from './individuals-folder.ts';

export const individuals = new IndividualsFolder(path.join(DATA_DIRECTORY, 'individuals'));

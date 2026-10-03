import { DATA_DIRECTORY } from './application-paths';
import { IdentityCatalog } from './identity-catalog';

export const herd = new IdentityCatalog(DATA_DIRECTORY);

import { loadCatalog, loadCount } from './.wuchale/js.proxy.sync.js';
import { serverRuntimes } from './server.js';

export const getRuntime = serverRuntimes(loadCatalog, loadCount);
export const getRuntimeRx = getRuntime;

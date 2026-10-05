import { loadCatalog, loadCount } from './.wuchale/main.proxy.sync.js';
import { serverRuntimes } from './server.js';

export const getRuntime = serverRuntimes(loadCatalog, loadCount);
export const getRuntimeRx = getRuntime;

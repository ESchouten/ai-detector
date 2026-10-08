import { registerLoaders } from 'wuchale/load-utils';
import { loadCatalog, loadCount } from './.wuchale/js.proxy.js';

export const getRuntime = registerLoaders('js', loadCatalog, loadCount);
export const getRuntimeRx = getRuntime;

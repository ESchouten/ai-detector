import { defaultCollection, registerLoaders } from 'wuchale/load-utils';
import { loadCatalog, loadCount } from './.wuchale/main.proxy.js';

/** @type import('wuchale/runtime').Runtime[] */
const runtimes = $state([]);

// Components read these reactively, so text follows the catalog loaded in +layout.ts.
export const getRuntime = registerLoaders(
	'main',
	loadCatalog,
	loadCount,
	defaultCollection(runtimes)
);
export const getRuntimeRx = getRuntime;

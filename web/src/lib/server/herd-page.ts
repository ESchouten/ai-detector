import { HerdError, type IdentityCatalog } from './identity-catalog.ts';
import { webLog } from './web-log.ts';

/** Preserve unreadable enrollment; the page must distinguish it from an empty herd. */
export async function readHerdPage(herd: IdentityCatalog) {
	try {
		return await herd.list();
	} catch (error) {
		if (!(error instanceof HerdError || error instanceof SyntaxError)) throw error;
		webLog.error('Could not read the saved herd. No herd files were changed.', error);
		return null;
	}
}

import { command, getRequestEvent, query } from '$app/server';
import { error } from '@sveltejs/kit';
import * as v from 'valibot';
import { installationImport } from '$lib/server/installation-import';
import { importError } from '$lib/server/installation-import/service';
import { chooseImportFolder } from '$lib/server/folder-picker';
import { isLocalDashboard } from '$lib/server/access';

/** Folders on this computer are offered only to the dashboard opened on this computer. */
function isLocal(): boolean {
	return isLocalDashboard(getRequestEvent().locals);
}

async function locally<T>(operation: () => Promise<T>): Promise<T> {
	if (!isLocal())
		error(
			403,
			'Open the localhost dashboard on the computer running AI Detector to import its files.'
		);
	try {
		return await operation();
	} catch (failure) {
		error(400, importError(failure));
	}
}

export const getImportStatus = query(async () => ({
	local: isLocal(),
	status: isLocal() ? await installationImport.getStatus() : null
}));

export const pickImportFolder = command(() => locally(chooseImportFolder));

export const cancelInstallationImport = command(() => locally(() => installationImport.cancel()));

export const inspectInstallation = command(v.pipe(v.string(), v.trim(), v.minLength(1)), (folder) =>
	locally(() => installationImport.inspect(folder))
);

export const importInstallation = command(
	v.object({
		id: v.string(),
		keepRecordings: v.boolean(),
		previousAppClosed: v.literal(true)
	}),
	(input) => locally(() => installationImport.start(input.id, input.keepRecordings))
);

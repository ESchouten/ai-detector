import { command, getRequestEvent, query } from '$app/server';
import { error } from '@sveltejs/kit';
import * as v from 'valibot';
import { installationImport } from '$lib/server/installation-import';
import { importError } from '$lib/server/installation-import/service';
import { chooseImportFolder } from '$lib/server/folder-picker';

function isLocal(): boolean {
	const event = getRequestEvent();
	return (
		['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(event.getClientAddress()) &&
		['localhost', '127.0.0.1', '[::1]'].includes(event.url.hostname)
	);
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

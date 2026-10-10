import { randomUUID } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import type { Configuration } from '../../schema.ts';

/**
 * Prepare both settings files before publishing either. A failed second rename
 * restores the first file; this does not provide power-loss atomicity across files.
 */
export async function writeConfiguration(
	files: { app: string; config: string },
	document: Configuration
): Promise<void> {
	const id = randomUUID();
	const nextApp = `${files.app}.${id}.next`;
	const nextConfig = `${files.config}.${id}.next`;
	const previousApp = `${files.app}.${id}.previous`;
	let hadApp = false;
	let retainBackup = false;
	try {
		await fs.mkdir(path.dirname(files.app), { recursive: true });
		await fs.mkdir(path.dirname(files.config), { recursive: true });
		let previous: Buffer | undefined;
		try {
			previous = await fs.readFile(files.app);
		} catch (error) {
			if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
		}
		if (previous !== undefined) {
			await fs.writeFile(previousApp, previous, { mode: 0o600 });
			hadApp = true;
		}
		await fs.writeFile(nextApp, JSON.stringify(document.app, null, 2) + '\n', { mode: 0o600 });
		await fs.writeFile(nextConfig, JSON.stringify(document.config, null, 2) + '\n', {
			mode: 0o600
		});
		await fs.rename(nextApp, files.app);
		try {
			await fs.rename(nextConfig, files.config);
		} catch (failure) {
			try {
				if (hadApp) await fs.rename(previousApp, files.app);
				else await fs.rm(files.app);
			} catch (rollbackFailure) {
				retainBackup = true;
				throw new AggregateError(
					[failure, rollbackFailure],
					`Settings could not be saved or restored. Recovery is required: ${hadApp ? `restore ${files.app} from ${previousApp}` : `remove the newly created ${files.app}`}.`,
					{ cause: failure }
				);
			}
			throw failure;
		}
	} finally {
		const temporary = [nextApp, nextConfig, ...(retainBackup ? [] : [previousApp])];
		await Promise.all(
			temporary.map((file) =>
				fs.rm(file, { force: true }).catch((error: unknown) => {
					// Temporary-file cleanup must not turn a committed save into a failed save.
					console.error(`Could not remove temporary settings file ${file}:`, error);
				})
			)
		);
	}
}

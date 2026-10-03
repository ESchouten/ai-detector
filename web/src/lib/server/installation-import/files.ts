import { constants } from 'node:fs';
import {
	copyFile,
	lstat,
	mkdir,
	readdir,
	realpath,
	rename,
	rm,
	stat,
	statfs
} from 'node:fs/promises';
import path from 'node:path';
import { ConfigurationError } from '../../configuration.ts';
import type { ReferencedFile } from './configuration.ts';

export interface ImportFile extends ReferencedFile {
	bytes: number;
	modified: number;
}

export function contains(root: string, file: string): boolean {
	const relative = path.relative(root, file);
	return (
		relative === '' ||
		(!relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative))
	);
}

export async function fileInfo(file: ReferencedFile): Promise<ImportFile> {
	const info = await stat(file.source);
	if (!info.isFile()) throw new ConfigurationError(`Expected a file: ${file.source}`);
	return { ...file, bytes: info.size, modified: info.mtimeMs };
}

/** Selected herd references must be regular files beneath the chosen installation. */
export async function containedFile(root: string, relative: string): Promise<ImportFile> {
	const source = path.join(root, relative);
	if (!contains(root, source)) throw new ConfigurationError('Invalid imported file path.');
	let current = root;
	for (const part of relative.split(path.sep)) {
		current = path.join(current, part);
		if ((await lstat(current)).isSymbolicLink())
			throw new ConfigurationError(
				`The herd contains a symbolic link at ${relative}. Select a folder with the original files.`
			);
	}
	return fileInfo({ source, relative });
}

/** Walk recording and preset folders without following links out of the selected installation. */
export async function collectFiles(root: string, relative: string): Promise<ImportFile[]> {
	const directory = path.join(root, relative);
	let entries;
	try {
		if ((await lstat(directory)).isSymbolicLink())
			throw new ConfigurationError(
				`The old folder contains a symbolic link at ${relative}. Select a folder with the original files.`
			);
		entries = await readdir(directory, { withFileTypes: true });
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === 'ENOENT') return [];
		throw error;
	}
	const files: ImportFile[] = [];
	for (const entry of entries) {
		const next = path.join(relative, entry.name);
		if (entry.isSymbolicLink())
			throw new ConfigurationError(
				`The old folder contains a symbolic link at ${next}. Select a folder with the original files.`
			);
		if (entry.isDirectory()) files.push(...(await collectFiles(root, next)));
		else if (entry.isFile())
			files.push(await fileInfo({ source: path.join(root, next), relative: next }));
	}
	return files;
}

export async function availableSpace(directory: string, bytes: number): Promise<void> {
	await mkdir(directory, { recursive: true });
	const disk = await statfs(directory);
	if (disk.bavail * disk.bsize < bytes)
		throw new ConfigurationError(
			'There is not enough free space. Free some space or keep recordings in their current folder.'
		);
}

export async function exists(file: string): Promise<boolean> {
	try {
		await lstat(file);
		return true;
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === 'ENOENT') return false;
		throw error;
	}
}

export async function verifySource(file: ImportFile): Promise<void> {
	const current = await stat(file.source);
	if (current.size !== file.bytes || current.mtimeMs !== file.modified)
		throw new ConfigurationError(
			'The old installation changed during import. Stop the old detector and choose its folder again.'
		);
}

/** A completed file is renamed into staging, so an interrupted copy is never mistaken for complete. */
export async function copyToStaging(file: ImportFile, staging: string): Promise<void> {
	await verifySource(file);
	const destination = path.join(staging, file.relative);
	if (await exists(destination)) {
		if ((await stat(destination)).size === file.bytes) return;
		throw new ConfigurationError(
			'An incomplete import file has changed. Choose the old folder again to restart the import.'
		);
	}
	await mkdir(path.dirname(destination), { recursive: true });
	const temporary = path.join(staging, '.copying');
	try {
		await copyFile(file.source, temporary, constants.COPYFILE_FICLONE);
		await verifySource(file);
		await rename(temporary, destination);
	} finally {
		await rm(temporary, { force: true });
	}
}

export async function sourceDirectory(input: string, destination: string): Promise<string> {
	const source = await realpath(input);
	if (!(await stat(source)).isDirectory())
		throw new ConfigurationError(
			'Choose the folder containing config.json, rather than the file itself.'
		);
	const target = await realpath(destination);
	if (contains(source, target) || contains(target, source))
		throw new ConfigurationError(
			'Choose the old installation, outside the new application data folder.'
		);
	return source;
}

import { mkdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import writeFileAtomic from 'write-file-atomic';

export async function readJson<T>(file: string, missing: T | null = null): Promise<T | null> {
	try {
		return JSON.parse(await readFile(file, 'utf8')) as T;
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === 'ENOENT') return missing;
		throw error;
	}
}

export async function writeJson(file: string, value: unknown): Promise<void> {
	await mkdir(path.dirname(file), { recursive: true });
	await writeFileAtomic(file, JSON.stringify(value, null, 2) + '\n', {
		mode: 0o600
	});
}

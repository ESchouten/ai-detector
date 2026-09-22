import { randomUUID } from 'node:crypto';
import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';

export async function readJson<T>(file: string): Promise<T | null> {
	try {
		return JSON.parse(await readFile(file, 'utf8')) as T;
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null;
		throw error;
	}
}

export async function writeJson(file: string, value: unknown): Promise<void> {
	await mkdir(path.dirname(file), { recursive: true });
	const temporary = `${file}.${randomUUID()}.tmp`;
	try {
		await writeFile(temporary, JSON.stringify(value, null, 2) + '\n', { mode: 0o600 });
		await rename(temporary, file);
	} finally {
		await rm(temporary, { force: true });
	}
}

import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import type { TestContext } from 'node:test';
import { fileURLToPath } from 'node:url';
import { ManagedDetector } from '../../src/lib/server/managed-detector.ts';

export const executable = fileURLToPath(new URL('../fixtures/detector.mjs', import.meta.url));

/** The fixture detector, managed in a data folder of its own; both are gone after the test. */
export async function managedDetector(t: TestContext) {
	// A space in the folder name, as a farmer's own user folder may have.
	const directory = await mkdtemp(path.join(tmpdir(), 'managed detector '));
	const detector = new ManagedDetector({ executable, dataDirectory: directory });
	t.after(async () => {
		await detector.stop();
		await rm(directory, { recursive: true, force: true });
	});
	return { detector, directory };
}

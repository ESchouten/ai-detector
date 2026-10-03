import path from 'node:path';
import type { IdentityCatalog } from './identity-catalog.ts';
import { containedFile, exists } from './installation-import/files.ts';

/** Select only confirmed enrollment; caches and unreviewed sightings are disposable. */
export async function confirmedHerdFiles(herd: IdentityCatalog) {
	const root = path.dirname(herd.directory);
	const catalogPath = path.join('identities', 'catalog.json');
	if (!(await exists(path.join(root, catalogPath)))) return null;
	const files = [await containedFile(root, catalogPath)];
	const snapshot = await herd.snapshot();
	for (const sighting of snapshot.sightings) {
		files.push(await containedFile(root, path.join('identities', 'images', `${sighting.id}.jpg`)));
		files.push(
			await containedFile(root, path.join('identities', 'sightings', `${sighting.id}.json`))
		);
	}
	return { ...snapshot, files };
}

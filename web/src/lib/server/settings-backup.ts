import type { ConfigurationStore } from './configuration/store.ts';
import type { IdentityCatalog } from './identity-catalog.ts';
import { confirmedHerdFiles } from './herd-backup.ts';
import { zipDownload } from './zip-download.ts';

export async function backupSettings(
	configuration: ConfigurationStore,
	herd: IdentityCatalog,
	request: Request
): Promise<Response> {
	// Read both documents through the settings queue, so a save cannot split the snapshot.
	const { config, app } = await configuration.read();
	delete app.devices;
	const enrollment = await confirmedHerdFiles(herd);
	return zipDownload(
		`AI-Detector-settings-${new Date().toISOString().slice(0, 10)}.zip`,
		[
			{ name: 'config.json', content: JSON.stringify(config, null, 2) + '\n' },
			{ name: 'app.json', content: JSON.stringify(app, null, 2) + '\n' },
			...(enrollment
				? [
						{
							name: 'identities/catalog.json',
							content: JSON.stringify(enrollment.catalog, null, 2) + '\n'
						},
						...enrollment.sightings.map((sighting) => ({
							name: `identities/sightings/${sighting.id}.json`,
							content: JSON.stringify(sighting, null, 2) + '\n'
						})),
						...enrollment.files
							.filter((file) => file.relative.endsWith('.jpg'))
							.map((file) => ({
								name: file.relative.replaceAll('\\', '/'),
								file: file.source
							}))
					]
				: []),
			{
				name: 'README.txt',
				content: `AI Detector settings backup

Includes cameras, detectors, alert settings and the confirmed herd with its
reference photos. Saved passwords and tokens are included. Keep this ZIP private.

To restore into a new installation, extract the ZIP, open Settings, choose
Use existing setup and select the extracted folder. Review the imported setup
before starting monitoring. Existing setups are never overwritten by import.

Unconfirmed cow photos, recognition caches, recordings, downloaded models,
local video sources, custom preset files and
computer startup preferences and connected-device access are not included. Keep any local model or video
files referenced by config.json alongside this backup, at their original
relative paths, or update those paths before importing on another computer.
`
			}
		],
		request
	);
}

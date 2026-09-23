import { existsSync } from 'node:fs';
import path from 'node:path';
import { DATA_DIRECTORY, EXECUTABLE_DIRECTORY, PACKAGED } from './application-paths';
import { readJson } from './json-file';
import { ManagedDetector } from './managed-detector';
import type { RuntimeStatus } from '../runtime';

let detector: ManagedDetector | null = null;
let initialization: Promise<void> | undefined;

export function initializeDetector(): Promise<void> {
	return (initialization ??= initialize());
}

async function initialize(): Promise<void> {
	const executable =
		process.env.AIDETECTOR_EXECUTABLE ??
		path.join(
			EXECUTABLE_DIRECTORY,
			'detector',
			process.platform === 'win32' ? 'aidetector.exe' : 'aidetector'
		);
	if (!process.env.AIDETECTOR_EXECUTABLE && (!PACKAGED || !existsSync(executable))) return;
	detector = new ManagedDetector({ executable, dataDirectory: DATA_DIRECTORY });
	try {
		const bundle = await readJson<{ dockerImage?: string }>(
			path.join(EXECUTABLE_DIRECTORY, 'application.json')
		);
		detector = new ManagedDetector({
			executable,
			dataDirectory: DATA_DIRECTORY,
			dockerImage: process.env.AIDETECTOR_DOCKER_IMAGE ?? bundle?.dockerImage
		});
		// The server must remain available while a first model/image is being prepared.
		void detector.initialize().catch((error) => detector?.fail(error));
	} catch (error) {
		detector.fail(error);
	}
	process.once('sveltekit:shutdown', () => detector?.stop(false));
}

export function managedDetector(): ManagedDetector | null {
	return detector;
}

export async function detectorStatus(): Promise<RuntimeStatus> {
	await detector?.refreshMetadata();
	return (
		detector?.status() ?? {
			managed: false,
			mode: 'auto',
			selected: null,
			phase: 'stopped',
			message:
				'This web server uses a separately managed detector. Download the complete application to start and stop it here.',
			logs: '',
			dataDirectory: DATA_DIRECTORY,
			readiness: 'idle',
			cameras: []
		}
	);
}

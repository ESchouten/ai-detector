import { existsSync } from 'node:fs';
import path from 'node:path';
import { DATA_DIRECTORY, EXECUTABLE_DIRECTORY, PACKAGED } from './application-paths';
import { readJson } from './json-file';
import { ManagedDetector } from './managed-detector';
import type { RuntimeStatus } from '../runtime';
import { diskSpace } from './storage';
import { recordings } from './recordings';
import { webLog } from './web-log';
import { WatchHistory } from './watch-history';
import { watchState } from '../camera-history';

let detector: ManagedDetector | null = null;
let initialization: Promise<void> | undefined;
let storageCheckedAt = 0;
let storageWarning: string | undefined;
export const watchHistory = new WatchHistory(path.join(DATA_DIRECTORY, 'history'));

/** Every ten seconds is as precisely as a gap in the history is known. */
async function keepHistory(): Promise<void> {
	try {
		await watchHistory.start();
	} catch (error) {
		webLog.warn('Could not open the camera history', error);
		return;
	}
	const timer = setInterval(async () => {
		try {
			await detector?.refreshMetadata();
			await watchHistory.sample(
				(detector?.status().cameras ?? []).map(({ id, state }) => ({
					id,
					state: watchState(state)
				}))
			);
		} catch (error) {
			webLog.warn('Could not keep the camera history', error);
		}
	}, 10000);
	timer.unref();
}

export function initializeDetector(prepareConfiguration: () => Promise<unknown>): Promise<void> {
	return (initialization ??= initialize(prepareConfiguration));
}

async function initialize(prepareConfiguration: () => Promise<unknown>): Promise<void> {
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
		await prepareConfiguration();
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
	await keepHistory();
	process.once('sveltekit:shutdown', (reason?: string) => detector?.stop(false, reason));
	process.once('aidetector:launcher-disconnected', () => {
		detector?.log.append(
			`${new Date().toISOString()} Native launcher disconnected; monitoring continues. Reopen AI Detector to restore the menu.\n`
		);
		void detector?.log.flush();
	});
}

export function managedDetector(): ManagedDetector | null {
	return detector;
}

export async function detectorStatus(): Promise<RuntimeStatus> {
	await detector?.refreshMetadata();
	if (Date.now() - storageCheckedAt > 30000) {
		storageCheckedAt = Date.now();
		try {
			const space = await diskSpace(recordings.directory);
			storageWarning = space.low
				? `Storage is almost full (${(space.available / 1024 ** 3).toFixed(1)} GB free). Free space in Settings → Storage so recordings can continue.`
				: undefined;
		} catch (error) {
			webLog.warn('Could not check recording storage', error);
		}
	}
	const status: RuntimeStatus = detector?.status() ?? {
		managed: false,
		mode: 'auto',
		selected: null,
		phase: 'stopped',
		message:
			'This web server uses a separately managed detector. Download the complete application to start and stop it here.',
		dataDirectory: DATA_DIRECTORY,
		readiness: 'idle',
		cameras: []
	};
	return { ...status, storageWarning };
}

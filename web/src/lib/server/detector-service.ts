import { existsSync } from 'node:fs';
import path from 'node:path';
import {
	APP_CONFIG_PATH,
	DATA_DIRECTORY,
	EXECUTABLE_DIRECTORY,
	PACKAGED
} from './application-paths';
import { ManagedDetector } from './managed-detector';
import { installationNotes, noteOutages } from './installation-notes';
import type { RuntimeStatus } from '../runtime';
import type { Configuration } from '../schema';
import { CameraRelocation, type RelocationWatch } from './cameras/relocation';
import { outageWatch } from './outage-alerts';
import { diskSpace } from './storage';
import { recordings } from './recordings';
import { sendTelegramNotice } from './telegram';
import { webLog } from './web-log';
import { WatchHistory } from './watch-history';
import { watchState } from '../camera-history';

let detector: ManagedDetector | null = null;
let initialization: Promise<void> | undefined;
let storageCheckedAt = 0;
let storageWarning: string | undefined;
export const watchHistory = new WatchHistory(path.join(DATA_DIRECTORY, 'history'));

/** Every ten seconds is as precisely as a gap in the history is known. */
async function keepHistory(): Promise<Date | undefined> {
	let stopped: Date | undefined;
	try {
		stopped = await watchHistory.start();
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
	return stopped;
}

/** How the settings follow a camera to a new address; the settings store does it. */
export type CameraMoves = Pick<RelocationWatch, 'remember' | 'relocate'>;

/**
 * While monitoring is on, the native shell keeps the computer awake, and the people who get a
 * camera's alerts hear when it is not watched, and cameras are followed to a new address.
 * `known` are the settings as read at the start, and `stopped` is when the application last ran.
 */
async function followMonitoring(
	monitored: ManagedDetector,
	settings: () => Promise<Configuration>,
	cameras: CameraMoves,
	known: Configuration | undefined,
	stopped: Date | undefined
): Promise<void> {
	// Settings that cannot be read are reported where they are edited.
	const notes: Awaited<ReturnType<typeof installationNotes>> = await installationNotes(
		APP_CONFIG_PATH
	).catch(() => ({}));
	const sample = outageWatch(
		{
			monitored,
			directory: DATA_DIRECTORY,
			noted: notes.outages,
			note: (outages) => noteOutages(APP_CONFIG_PATH, outages),
			settings,
			send: ({ token, chat }, text, silent) => sendTelegramNotice(token, chat, text, silent),
			warn: (message, error) => webLog.warn(message, error)
		},
		known,
		// The time the application did not run is an outage only if monitoring was switched on.
		notes.monitoring === true ? stopped?.getTime() : undefined
	);
	const relocation = new CameraRelocation({
		monitored,
		directory: DATA_DIRECTORY,
		settings,
		remember: cameras.remember,
		relocate: cameras.relocate,
		send: ({ token, chat }, text, silent) => sendTelegramNotice(token, chat, text, silent),
		log: (message) => webLog.info(message),
		warn: (message, error) => webLog.warn(message, error)
	});
	// Unknown at first, so that a shell that outlived an earlier server always hears the state.
	let awake: boolean | undefined;
	const timer = setInterval(() => {
		const monitoring = monitored.monitoring;
		if (monitoring !== awake) {
			awake = monitoring;
			for (const listener of process.rawListeners('aidetector:monitoring'))
				listener.call(process, monitoring);
		}
		// Whatever goes wrong with a notice must not take monitoring down with it.
		try {
			sample();
		} catch (error) {
			webLog.warn('Could not follow the cameras for outage notices', error);
		}
		void relocation.sample();
	}, 10000);
	timer.unref();
}

export function initializeDetector(
	prepareConfiguration: () => Promise<Configuration>,
	cameras: CameraMoves
): Promise<void> {
	return (initialization ??= initialize(prepareConfiguration, cameras));
}

async function initialize(
	prepareConfiguration: () => Promise<Configuration>,
	cameras: CameraMoves
): Promise<void> {
	const executable =
		process.env.AIDETECTOR_EXECUTABLE ??
		path.join(
			EXECUTABLE_DIRECTORY,
			'detector',
			process.platform === 'win32' ? 'aidetector.exe' : 'aidetector'
		);
	if (!process.env.AIDETECTOR_EXECUTABLE && (!PACKAGED || !existsSync(executable))) return;
	detector = new ManagedDetector({ executable, dataDirectory: DATA_DIRECTORY });
	let known: Configuration | undefined;
	try {
		known = await prepareConfiguration();
		// The server must remain available while a first model is being prepared.
		void detector.initialize().catch((error) => detector?.fail(error));
	} catch (error) {
		detector.fail(error);
	}
	await followMonitoring(detector, prepareConfiguration, cameras, known, await keepHistory());
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
		phase: 'stopped',
		message:
			'This web server uses a separately managed detector. Download the complete application to start and stop it here.',
		dataDirectory: DATA_DIRECTORY,
		readiness: 'idle',
		cameras: []
	};
	return { ...status, storageWarning };
}

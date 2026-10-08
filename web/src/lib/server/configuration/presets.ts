import { existsSync } from 'node:fs';
import path from 'node:path';
import { dev } from '$app/environment';
import type { DetectorPreset } from '../../schema.ts';
import { preview } from '../../version.ts';
import { DATA_DIRECTORY } from '../application-paths.ts';
import { webLog } from '../web-log.ts';
import { newerPresets } from './followed-presets.ts';
import { configuration } from './index.ts';
import { loadPresets } from './preset-files.ts';
import {
	modelAvailable,
	PUBLISHED_PRESETS,
	publishedPresets,
	withPublished
} from './published-presets.ts';

const bundledConfigurations = import.meta.glob('../../../../../config/detector/*.json', {
	eager: true,
	import: 'default'
});
const override = process.env.AIDETECTOR_PRESETS;
const directory = override ? path.resolve(override) : path.join(DATA_DIRECTORY, 'presets');
/**
 * Where newer presets are published; empty for none. Development and test builds keep the
 * presets they were built with, which may be ahead of the published ones.
 */
const source = process.env.AIDETECTOR_PRESETS_URL ?? (dev || preview ? '' : PUBLISHED_PRESETS);
const DAY = 24 * 60 * 60 * 1000;
/** As last fetched while this application runs. */
let published: DetectorPreset[] = [];

/** A folder of this installation's own presets replaces the bundled and the published ones. */
function hasOwnPresets(): boolean {
	return Boolean(override) || existsSync(directory);
}

export async function readPresets(): Promise<DetectorPreset[]> {
	const presets = await loadPresets(directory, override ? undefined : bundledConfigurations);
	return hasOwnPresets() ? presets : withPublished(presets, published);
}

/** The presets detectors follow: this installation's own, else the published ones, fetched now. */
async function followedPresets(signal: AbortSignal): Promise<DetectorPreset[]> {
	if (!source || hasOwnPresets()) return readPresets();
	published = await publishedPresets(source, signal);
	return published;
}

/**
 * Detectors that follow a preset take its newest settings, such as a newer model. When the
 * published presets cannot be fetched, or the new model cannot be downloaded, they keep the
 * settings they have.
 */
async function updateFollowedPresets(): Promise<void> {
	const signal = AbortSignal.timeout(10_000);
	try {
		const presets = await followedPresets(signal);
		const ready: DetectorPreset[] = [];
		for (const preset of newerPresets(await configuration.read(), presets)) {
			if (await modelAvailable(preset.detector, signal)) ready.push(preset);
			else webLog.warn(`The model of preset "${preset.name}" cannot be downloaded now.`);
		}
		for (const label of await configuration.followPresets(ready))
			console.info(`Detector "${label}" now has the current settings of its preset.`);
	} catch (error) {
		webLog.warn(`Could not check for newer presets: ${(error as Error).message}`, error);
	}
}

/** Before monitoring starts, and once a day while the application runs. */
export async function followPresets(): Promise<void> {
	await updateFollowedPresets();
	const daily = setInterval(() => void updateFollowedPresets(), DAY);
	daily.unref();
	process.once('sveltekit:shutdown', () => clearInterval(daily));
}

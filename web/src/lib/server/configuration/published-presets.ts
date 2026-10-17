import * as v from 'valibot';
import { ConfigurationError } from '../../configuration.ts';
import type { DetectorConfig, DetectorPreset } from '../../schema.ts';
import { webLog } from '../web-log.ts';
import { presetFromFile } from './preset-files.ts';

/** The folder the released application has always read its presets from. */
export const PUBLISHED_PRESETS =
	'https://api.github.com/repos/ESchouten/ai-detector/contents/config/detector?ref=main';

const folderListing = v.array(v.object({ name: v.string(), download_url: v.nullable(v.string()) }));

async function fetchJson(url: string, signal: AbortSignal): Promise<unknown> {
	const response = await fetch(url, {
		signal,
		headers: { Accept: 'application/vnd.github+json', 'User-Agent': 'ai-detector' }
	});
	if (!response.ok)
		throw new Error(/* @wc-ignore */ `${new URL(url).host} answered ${response.status}`);
	return response.json();
}

/**
 * The presets published for every installation, from a folder listing in GitHub's format.
 * A preset this version of the application cannot use is left out, so that an older
 * installation keeps what it has.
 */
export async function publishedPresets(
	url: string,
	signal: AbortSignal
): Promise<DetectorPreset[]> {
	const files = v.parse(folderListing, await fetchJson(url, signal));
	const presets = await Promise.all(
		files.map(async ({ name, download_url }) => {
			if (!name.endsWith('.json') || !download_url) return [];
			try {
				return [presetFromFile(name, await fetchJson(download_url, signal))];
			} catch (error) {
				if (!(error instanceof ConfigurationError)) throw error;
				webLog.warn(`Skipped a published preset this version cannot use. ${error.message}`);
				return [];
			}
		})
	);
	return presets.flat();
}

/** The presets to choose from: a published preset replaces the bundled one of the same name. */
export function withPublished(
	bundled: DetectorPreset[],
	published: DetectorPreset[]
): DetectorPreset[] {
	return [
		...published,
		...bundled.filter(({ id }) => !published.some((preset) => preset.id === id))
	].sort((a, b) => a.id.localeCompare(b.id, 'en'));
}

/**
 * Whether the model a preset names can be downloaded now. Detectors move to a preset only then:
 * a model that cannot be fetched would stop their monitoring. A model named without an address
 * is fetched by the detector's own library and is not checked.
 */
export async function modelAvailable(
	detector: DetectorConfig,
	signal: AbortSignal
): Promise<boolean> {
	const model = detector.yolo?.model;
	if (!model || !/^https?:\/\//i.test(model)) return true;
	try {
		const response = await fetch(model, { signal, headers: { Range: 'bytes=0-0' } });
		await response.body?.cancel();
		return response.ok;
	} catch {
		signal.throwIfAborted();
		return false;
	}
}

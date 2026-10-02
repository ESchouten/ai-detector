import { createHash } from 'node:crypto';
import { access, readFile, realpath } from 'node:fs/promises';
import path from 'node:path';
import { homedir } from 'node:os';
import * as v from 'valibot';
import { ConfigurationError, normalizeConfiguration } from '../../configuration.ts';
import type { Configuration } from '../../schema.ts';
import { upgradeVerificationKeys } from '../configuration/upgrade.ts';

const legacySchema = v.looseObject({
	detectors: v.array(
		v.looseObject({
			yolo: v.optional(
				v.nullable(v.looseObject({ strategy: v.optional(v.picklist(['LATEST', 'ALL'])) }))
			)
		})
	)
});

export interface ReferencedFile {
	source: string;
	relative: string;
}

async function readDocument(file: string, optional = false): Promise<unknown> {
	let content: string;
	try {
		content = await readFile(file, 'utf8');
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
		if (optional) return {};
		throw new ConfigurationError('Choose the old application folder containing config.json.');
	}
	try {
		return JSON.parse(content);
	} catch {
		throw new ConfigurationError(
			`${path.basename(file)} is not valid JSON. The original file has not been changed.`
		);
	}
}

/** Translate only known legacy options; the canonical validator rejects everything else. */
export async function readLegacyConfiguration(source: string): Promise<{
	document: Configuration;
	files: ReferencedFile[];
	notes: string[];
}> {
	const input = v.parse(legacySchema, await readDocument(path.join(source, 'config.json')));
	const notes: string[] = [];
	for (const detector of input.detectors) {
		if (detector.yolo?.strategy !== undefined) {
			delete detector.yolo.strategy;
			if (!notes.length)
				notes.push('Removed the old strategy option, which the previous detector did not use.');
		}
	}
	const document = normalizeConfiguration(
		upgradeVerificationKeys(input),
		await readDocument(path.join(source, 'app.json'), true)
	);
	delete document.app.devices;
	const files = new Map<string, ReferencedFile>();
	const references = new Map<string, string>();
	async function relocate(value: string, model = false): Promise<string> {
		if (/^[a-z][a-z\d+.-]*:\/\//i.test(value) || /^\d+$/.test(value)) return value;
		const existing = references.get(value);
		if (existing) return existing;
		const file = value.startsWith('~/')
			? path.join(homedir(), value.slice(2))
			: path.resolve(source, value);
		try {
			await access(file);
		} catch (error) {
			// Standard YOLO model names can be downloaded by Ultralytics on first use.
			if (
				model &&
				path.basename(value) === value &&
				(error as NodeJS.ErrnoException).code === 'ENOENT'
			) {
				notes.push(
					`The model ${value} is not in the old folder. Ultralytics will try to download it when monitoring starts.`
				);
				references.set(value, value);
				return value;
			}
			throw new ConfigurationError(
				`A local ${model ? 'model' : 'video'} file is missing: ${value}. Restore it before importing.`
			);
		}
		const resolved = await realpath(file);
		const key = createHash('sha256').update(resolved).digest('hex').slice(0, 16);
		const relative = path.join('imported-files', key, path.basename(resolved));
		files.set(relative, { source: resolved, relative });
		references.set(value, relative);
		// ONNX external tensors commonly accompany the model in this sibling file.
		if (model && resolved.endsWith('.onnx')) {
			try {
				await access(`${resolved}.data`);
				files.set(`${relative}.data`, { source: `${resolved}.data`, relative: `${relative}.data` });
			} catch (error) {
				if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
			}
		}
		return relative;
	}
	for (const detector of document.config.detectors) {
		if (detector.yolo) detector.yolo.model = await relocate(detector.yolo.model, true);
		detector.detection.source = await Promise.all(
			detector.detection.source.map((value) => relocate(value))
		);
	}
	for (const camera of document.app.streams) {
		camera.source = await relocate(camera.source);
		delete camera.setup;
	}
	return { document, files: [...files.values()], notes };
}

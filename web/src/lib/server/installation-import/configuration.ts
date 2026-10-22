import { createHash } from 'node:crypto';
import { access, readFile, realpath } from 'node:fs/promises';
import path from 'node:path';
import { homedir } from 'node:os';
import * as v from 'valibot';
import { ConfigurationError, normalizeConfiguration } from '../../configuration.ts';
import type { Configuration } from '../../schema.ts';
import { isMissingFile } from '../json-file.ts';
import { migrateAppMetadata } from './metadata.ts';

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

function issueField(issue: v.BaseIssue<unknown>): string {
	// Custom API header names are user input too, not schema field names.
	const steps = issue.path ?? [];
	const headers = steps.findIndex((item) => item.key === 'headers');
	return (
		steps
			.slice(0, headers < 0 ? steps.length : headers + 1)
			.map((item) => String(item.key))
			.join('.') || '(root)'
	);
}

function invalidSettings(
	file: string,
	issues: readonly v.BaseIssue<unknown>[]
): ConfigurationError {
	const fields = [...new Set(issues.map(issueField))].join(', ');
	// Validator messages can quote input values, including camera URLs and credentials.
	return new ConfigurationError(`Check ${file}: ${fields}. These settings are invalid or missing.`);
}

async function readDocument(file: string, optional = false): Promise<unknown> {
	let content: string;
	try {
		content = await readFile(file, 'utf8');
	} catch (error) {
		if (!isMissingFile(error)) throw error;
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
	const parsed = v.safeParse(legacySchema, await readDocument(path.join(source, 'config.json')));
	if (!parsed.success) throw invalidSettings('config.json', parsed.issues);
	const input = parsed.output;
	const notes: string[] = [];
	for (const detector of input.detectors) {
		if (detector.yolo?.strategy !== undefined) {
			delete detector.yolo.strategy;
			if (!notes.length)
				notes.push('Removed the old strategy option, which the previous detector did not use.');
		}
	}
	const app = migrateAppMetadata(await readDocument(path.join(source, 'app.json'), true), notes);
	let document: Configuration;
	try {
		document = normalizeConfiguration(input, app);
	} catch (error) {
		if (v.isValiError(error)) throw invalidSettings('app.json', error.issues);
		if (error instanceof ConfigurationError)
			throw new ConfigurationError(`config.json: ${error.message}`, { cause: error });
		throw error;
	}
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
			if (model && path.basename(value) === value && isMissingFile(error)) {
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
				if (!isMissingFile(error)) throw error;
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
	}
	return { document, files: [...files.values()], notes };
}

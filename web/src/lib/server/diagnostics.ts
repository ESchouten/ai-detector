import { readdir, readFile, lstat } from 'node:fs/promises';
import { arch, cpus, platform, release, totalmem } from 'node:os';
import path from 'node:path';
import { stripVTControlCharacters } from 'node:util';
import { preview, version } from '../version.ts';
import { readJson } from './json-file.ts';
import { sanitizeTextForLogs } from './runtime-logs.ts';
import type { ZipEntry } from './zip-download.ts';

const SECRET_FIELD = /^(?:key|token|password|secret|headers|authorization)$/i;

/** Redact structured settings and the same credentials wherever a library printed them. */
function diagnosticRedactor(...documents: unknown[]) {
	const secrets = new Set<string>();
	function settings(value: unknown, sensitive = false): unknown {
		if (typeof value === 'string') {
			if (sensitive) {
				if (value.length >= 4) secrets.add(value);
				const credential = value.replace(/^(?:Bearer|Basic)\s+/i, '');
				if (credential.length >= 4) secrets.add(credential);
				return '***';
			}
			return sanitizeTextForLogs(value);
		}
		if (Array.isArray(value)) return value.map((item) => settings(item, sensitive));
		if (value && typeof value === 'object')
			return Object.fromEntries(
				Object.entries(value).map(([key, item]) => [
					key,
					settings(item, sensitive || SECRET_FIELD.test(key))
				])
			);
		return value;
	}
	const redacted = documents.map((document) => settings(document));
	const ordered = Array.from(secrets).sort((a, b) => b.length - a.length);
	return {
		documents: redacted,
		text(value: string) {
			for (const secret of ordered) value = value.replaceAll(secret, '***');
			return sanitizeTextForLogs(stripVTControlCharacters(value));
		}
	};
}

async function entries(directory: string) {
	try {
		return await readdir(directory, { withFileTypes: true });
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === 'ENOENT') return [];
		throw error;
	}
}

/** Collect support evidence only: never images, session credentials or raw settings backups. */
export async function* diagnosticFiles(
	directory: string,
	runtime: unknown
): AsyncGenerator<ZipEntry> {
	const documents = await Promise.all(
		['config.json', 'app.json'].map(async (name) => {
			try {
				const document = await readJson<Record<string, unknown>>(path.join(directory, name));
				if (name === 'app.json' && document) delete document.devices;
				return document;
			} catch (error) {
				return { unreadable: (error as Error).name };
			}
		})
	);
	const redact = diagnosticRedactor(...documents);
	yield {
		name: 'README.txt',
		content:
			'AI Detector diagnostics\n\nIncludes available rotated logs, the eight latest TensorRT build logs, runtime details and redacted settings. No recordings are included. Review the files before sharing: logs may include local paths and camera addresses.\n'
	};
	yield {
		name: 'system.json',
		content: redact.text(
			JSON.stringify(
				{
					version,
					preview,
					platform: platform(),
					release: release(),
					architecture: arch(),
					cpu: cpus()[0]?.model,
					memory: totalmem(),
					node: process.version,
					runtime
				},
				null,
				2
			)
		)
	};
	for (const [index, name] of ['config.json', 'app.json'].entries())
		yield { name: `settings/${name}`, content: JSON.stringify(redact.documents[index], null, 2) };
	for (const entry of await entries(path.join(directory, 'logs'))) {
		if (!entry.isFile() || !/\.log(?:\.\d+)?$/.test(entry.name)) continue;
		yield {
			name: `logs/${entry.name}`,
			content: redact.text(await readFile(path.join(directory, 'logs', entry.name), 'utf8'))
		};
	}
	const engines = path.join(directory, 'models', 'prepared', 'tensorrt');
	const builds: { file: string; name: string; modified: number }[] = [];
	for (const entry of await entries(engines)) {
		if (!entry.isDirectory() || !/^[a-f0-9]{64}$/.test(entry.name)) continue;
		const file = path.join(engines, entry.name, 'build.log');
		try {
			const info = await lstat(file);
			if (info.isFile()) builds.push({ file, name: entry.name, modified: info.mtimeMs });
		} catch (error) {
			if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
		}
	}
	for (const build of builds.sort((a, b) => b.modified - a.modified).slice(0, 8))
		yield {
			name: `tensorrt/${build.name}/build.log`,
			content: redact.text(await readFile(build.file, 'utf8'))
		};
}

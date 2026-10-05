import { randomUUID } from 'node:crypto';
import { mkdir, rename, rm, symlink } from 'node:fs/promises';
import path from 'node:path';
import { isValiError } from 'valibot';
import { ConfigurationError } from '../../configuration.ts';
import type { ImportStatus, ImportSummary } from '../../installation-import.ts';
import { STAGES, type Configuration } from '../../schema.ts';
import type { ConfigurationStore } from '../configuration/store.ts';
import { readJson, writeJson } from '../json-file.ts';
import { serialQueue } from '../serial.ts';
import { readLegacyConfiguration } from './configuration.ts';
import {
	availableSpace,
	collectFiles,
	copyToStaging,
	exists,
	fileInfo,
	sourceDirectory,
	verifySource,
	type ImportFile
} from './files.ts';

interface ImportJob {
	summary: ImportSummary;
	document: Configuration;
	files: ImportFile[];
	settings: ImportFile[];
	keepRecordings?: boolean;
	publishing?: boolean;
}

/** Copies into a private staging folder; settings become visible only after all files are ready. */
export class InstallationImport {
	private job?: ImportJob;
	private status: ImportStatus = { phase: 'idle', copiedBytes: 0, totalBytes: 0 };
	private readonly serial = serialQueue();
	private work: Promise<void> | null = null;
	private readonly staging: string;
	private readonly manifest: string;
	private readonly ready: Promise<void>;
	private readonly destination: string;
	private readonly configuration: ConfigurationStore;

	constructor(destination: string, configuration: ConfigurationStore) {
		this.destination = destination;
		this.configuration = configuration;
		this.staging = path.join(destination, '.installation-import');
		this.manifest = path.join(this.staging, 'job.json');
		this.ready = this.restore();
	}

	private async restore(): Promise<void> {
		this.job = (await readJson<ImportJob>(this.manifest)) ?? undefined;
		if (this.job)
			this.status = {
				phase: 'ready',
				summary: this.job.summary,
				copiedBytes: 0,
				totalBytes: this.job.summary.bytes,
				message:
					this.job.keepRecordings === undefined
						? undefined
						: 'An unfinished import is ready to resume.',
				keepRecordings: this.job.keepRecordings,
				canRestart: !this.job.publishing
			};
	}

	/** Each operation first waits for an unfinished import to be read back, when its turn comes. */
	private enqueue<T>(operation: () => Promise<T>): Promise<T> {
		return this.serial(() => this.ready.then(operation));
	}

	async getStatus(): Promise<ImportStatus> {
		await this.ready;
		return structuredClone(this.status);
	}

	cancel(): Promise<void> {
		return this.enqueue(async () => {
			if (this.work || this.job?.publishing)
				throw new ConfigurationError('Finish the current import before leaving setup.');
			await rm(this.staging, { recursive: true, force: true });
			this.job = undefined;
			this.status = { phase: 'idle', copiedBytes: 0, totalBytes: 0 };
		});
	}

	inspect(input: string): Promise<ImportSummary> {
		return this.enqueue(async () => {
			if (this.work || this.job?.publishing)
				throw new ConfigurationError('Finish the current import before choosing another folder.');
			await this.requireEmptySetup();
			await mkdir(this.destination, { recursive: true });
			const source = await sourceDirectory(input, this.destination);
			const { document, files: references, notes } = await readLegacyConfiguration(source);
			const [recordings, presets, files, settings] = await Promise.all([
				collectFiles(source, 'detections'),
				collectFiles(source, 'presets'),
				Promise.all(references.map(fileInfo)),
				this.settingsFiles(source)
			]);
			const allFiles = [...recordings, ...presets, ...files];
			const summary: ImportSummary = {
				id: randomUUID(),
				source,
				destination: this.destination,
				cameras: document.app.streams.length,
				detectors: document.config.detectors.length,
				recordings: recordings.filter(isRecording).length,
				bytes: allFiles.reduce((total, file) => total + file.bytes, 0),
				recordingBytes: recordings.reduce((total, file) => total + file.bytes, 0),
				notes
			};
			await this.requireAvailableFolders(allFiles);
			await rm(this.staging, { recursive: true, force: true });
			await mkdir(this.staging, { mode: 0o700 });
			this.job = { summary, document, files: allFiles, settings };
			await writeJson(this.manifest, this.job);
			this.status = { phase: 'ready', summary, copiedBytes: 0, totalBytes: summary.bytes };
			return summary;
		});
	}

	start(id: string, keepRecordings: boolean): Promise<void> {
		return this.enqueue(async () => {
			const job = this.job;
			if (!job || job.summary.id !== id)
				throw new ConfigurationError('Choose the previous installation again.');
			if (this.work) return;
			if (job.keepRecordings !== undefined && job.keepRecordings !== keepRecordings)
				throw new ConfigurationError(
					'Resume with the same recording option, or choose the folder again.'
				);
			job.keepRecordings = keepRecordings;
			await writeJson(this.manifest, job);
			this.status = {
				phase: 'copying',
				summary: job.summary,
				copiedBytes: 0,
				totalBytes: job.summary.bytes - (keepRecordings ? job.summary.recordingBytes : 0),
				keepRecordings
			};
			this.work = this.run(job)
				.catch((error: unknown) => {
					this.status.phase = 'failed';
					this.status.message = importError(error);
					this.status.canRestart = !job.publishing;
				})
				.finally(() => {
					this.work = null;
				});
		});
	}

	/** Used by shutdown/tests to wait for the current transfer. */
	async settled(): Promise<void> {
		await this.work;
	}

	private async requireEmptySetup(): Promise<void> {
		const { config, app } = await this.configuration.read();
		if (config.detectors.length || app.streams.length || app.telegrams.length || app.llms.length)
			throw new ConfigurationError(
				'This application already has a setup. Import is available before adding cameras or detectors.'
			);
	}

	private async settingsFiles(source: string): Promise<ImportFile[]> {
		const files = ['config.json'];
		if (await exists(path.join(source, 'app.json'))) files.push('app.json');
		return Promise.all(
			files.map((relative) => fileInfo({ source: path.join(source, relative), relative }))
		);
	}

	private async requireAvailableFolders(files: ImportFile[]): Promise<void> {
		for (const folder of folders(files)) {
			if (await exists(path.join(this.destination, folder)))
				throw new ConfigurationError(
					`The new application already has a ${folder} folder. Import will not overwrite existing data.`
				);
		}
	}

	private async run(job: ImportJob): Promise<void> {
		for (const file of job.settings) await verifySource(file);
		if (!job.publishing) await this.stage(job);
		this.status.message = 'Saving your setup…';
		await this.configuration.initialize(job.document, () => this.publish(job), job.publishing);
		// Remove the private manifest (which contains configuration credentials) after commit.
		await rm(this.staging, { recursive: true, force: true });
		this.job = undefined;
		this.status.phase = 'complete';
		this.status.copiedBytes = this.status.totalBytes;
		delete this.status.message;
	}

	private async stage(job: ImportJob): Promise<void> {
		const files = job.files.filter((file) => !job.keepRecordings || !isArchiveFile(file));
		const payload = path.join(this.staging, 'files');
		const remaining = await Promise.all(
			files.map(async (file) =>
				(await exists(path.join(payload, file.relative))) ? 0 : file.bytes
			)
		);
		await availableSpace(
			this.destination,
			remaining.reduce((sum, size) => sum + size, 0)
		);
		for (const file of files) {
			await copyToStaging(file, payload);
			this.status.copiedBytes += file.bytes;
		}
		for (const file of [...job.settings, ...job.files]) await verifySource(file);
		if (job.keepRecordings && job.files.some(isArchiveFile)) {
			await mkdir(payload, { recursive: true });
			const link = path.join(payload, 'detections');
			if (!(await exists(link)))
				await symlink(
					path.join(job.summary.source, 'detections'),
					link,
					process.platform === 'win32' ? 'junction' : 'dir'
				);
		}
	}

	private async publish(job: ImportJob): Promise<void> {
		if (!job.publishing) {
			await this.requireAvailableFolders(job.files);
			// Record ownership before the first rename so a restart can finish publishing.
			job.publishing = true;
			await writeJson(this.manifest, job);
		}
		for (const folder of folders(job.files)) {
			const staged = path.join(this.staging, 'files', folder);
			const destination = path.join(this.destination, folder);
			if (await exists(staged)) await rename(staged, destination);
			else if (!(await exists(destination)))
				throw new ConfigurationError(
					'An imported folder is missing. Restore the drive before resuming the import.'
				);
		}
	}
}

function folders(files: ImportFile[]): string[] {
	return [...new Set(files.map((file) => file.relative.split(path.sep)[0]))];
}

function isArchiveFile(file: ImportFile): boolean {
	return file.relative.startsWith(`detections${path.sep}`);
}

function isRecording(file: ImportFile): boolean {
	const parts = file.relative.split(path.sep);
	return (
		parts.length === 5 && STAGES.some((stage) => stage === parts[2]) && parts[4] === 'metadata.json'
	);
}

export function importError(error: unknown): string {
	if (error instanceof ConfigurationError || isValiError(error)) return error.message;
	const code = (error as NodeJS.ErrnoException).code;
	if (code === 'ENOENT')
		return 'The old folder or a file could not be found. Connect the drive and choose the folder again.';
	if (code === 'ENOSPC')
		return 'There is not enough free space. Free some space and resume the import.';
	if (code === 'EACCES' || code === 'EPERM')
		return 'AI Detector cannot access this folder. Check its permissions and try again.';
	return 'The import could not finish. Your original files are unchanged. Check the drive and try again.';
}

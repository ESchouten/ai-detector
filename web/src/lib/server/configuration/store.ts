import type * as v from 'valibot';
import { isDeepStrictEqual } from 'node:util';
import {
	DEFAULT_SCHEMA_URL,
	type Config,
	type Configuration,
	type LlmConnection
} from '../../schema.ts';
import { readJson, writeJson } from '../json-file.ts';
import {
	alertsInput,
	ConfigurationError,
	cameraInput,
	detectorInput,
	normalizeConfig,
	normalizeConfiguration,
	streamInput,
	telegramInput
} from '../../configuration.ts';
import { identifyCameras, saveCamera, removeCamera } from './cameras.ts';
import { writeConfiguration } from './files.ts';
import { upgradeVerificationKeys } from './upgrade.ts';
import { saveDetector, deleteDetector } from './detectors.ts';
import { saveStream, deleteStream, reorderStream } from './streams.ts';
import { saveTelegram, deleteTelegram, saveAlerts } from './telegrams.ts';
import { saveLlm, deleteLlm } from './llms.ts';
import { replaceConnections, replaceDetectorConfig, settingsRevision } from './advanced.ts';
import { recordArchiveCheck, finishCameraSetup } from './camera-setup.ts';

interface Runtime {
	validate(config: Config): Promise<void>;
	apply(): Promise<void>;
	stop(): Promise<void>;
	fail(error: unknown): void;
}

export class ConfigurationStore {
	private pending: Promise<unknown> = Promise.resolve();
	private files: { config: string; app: string };
	private runtime: () => Runtime | null;

	constructor(files: { config: string; app: string }, runtime: () => Runtime | null = () => null) {
		this.files = files;
		this.runtime = runtime;
	}

	private enqueue<T>(operation: () => Promise<T>): Promise<T> {
		const result = this.pending.then(operation);
		this.pending = result.catch(() => undefined);
		return result;
	}

	private async load(): Promise<Configuration> {
		const [config, app] = await Promise.all([
			readJson<unknown>(this.files.config, { $schema: DEFAULT_SCHEMA_URL, detectors: [] }),
			readJson<unknown>(this.files.app, {})
		]);
		try {
			const upgraded = upgradeVerificationKeys(config);
			const document = identifyCameras(normalizeConfiguration(upgraded, app));
			if (upgraded !== config) await writeConfiguration(this.files, document);
			return document;
		} catch (error) {
			if (error instanceof ConfigurationError)
				throw new ConfigurationError(`${this.files.config}: ${error.message}`, { cause: error });
			throw error;
		}
	}

	read(): Promise<Configuration> {
		return this.enqueue(() => this.load());
	}

	/** Seed onboarding without starting monitoring or sending alerts. */
	initialize(
		document: Configuration,
		publishFiles: () => Promise<void>,
		resuming = false
	): Promise<void> {
		return this.enqueue(async () => {
			const next = identifyCameras(normalizeConfiguration(document.config, document.app));
			const current = await this.load();
			if (resuming && isDeepStrictEqual(current, next)) return;
			const recoveringApp = resuming && isDeepStrictEqual(await readJson(this.files.app), next.app);
			if (
				current.config.detectors.length ||
				(!recoveringApp &&
					(current.app.streams.length || current.app.telegrams.length || current.app.llms.length))
			)
				throw new ConfigurationError(
					'This application already has a setup. Import into a new installation to avoid replacing your settings.'
				);
			if (next.config.detectors.length) await this.runtime()?.validate(next.config);
			await publishFiles();
			await writeConfiguration(this.files, next);
		});
	}

	private async persist(input: { config: unknown; app: unknown }): Promise<void> {
		const { config, app } = identifyCameras(normalizeConfiguration(input.config, input.app));
		const previous = await readJson<unknown>(this.files.config);
		const configChanged =
			previous === null || !isDeepStrictEqual(normalizeConfig(previous), config);
		const runtime = this.runtime();
		if (configChanged && config.detectors.length) await runtime?.validate(config);
		if (!configChanged) {
			await writeJson(this.files.app, app);
			return;
		}
		await writeConfiguration(this.files, { config, app });
		if (!runtime) return;
		try {
			if (config.detectors.length) await runtime.apply();
			else await runtime.stop();
		} catch (error) {
			// Persistence succeeded. Report the operational failure through runtime status,
			// so a client does not retry an already saved camera or detector.
			runtime.fail(error);
		}
	}

	private update<T>(change: (document: Configuration) => T | Promise<T>): Promise<T> {
		return this.enqueue(async () => {
			const document = await this.load();
			const result = await change(document);
			await this.persist(document);
			return result;
		});
	}

	saveCamera(input: v.InferOutput<typeof cameraInput>, pictureVerifiedAt?: string) {
		return this.update((document) => saveCamera(document, input, pictureVerifiedAt));
	}

	removeCamera(id: string): Promise<void> {
		return this.update((document) => removeCamera(document, id));
	}

	saveAlerts(input: v.InferOutput<typeof alertsInput>): Promise<void> {
		return this.update((document) => saveAlerts(document, input));
	}

	saveLlm(input: LlmConnection & { original?: string }): Promise<void> {
		return this.update((document) => saveLlm(document, input));
	}

	deleteLlm(label: string): Promise<void> {
		return this.update((document) => deleteLlm(document, label));
	}

	recordArchiveCheck(id: string, signature: string, verifiedAt: string): Promise<void> {
		return this.update((document) => recordArchiveCheck(document, id, signature, verifiedAt));
	}

	finishSetup(monitoring: () => Promise<ReadonlySet<string>>): Promise<void> {
		return this.update(async (document) => {
			if (!document.app.streams.length)
				throw new ConfigurationError('Add a camera before finishing setup.');
			const monitored = await monitoring();
			for (const camera of document.app.streams) {
				finishCameraSetup(document, camera.id!, monitored.has(camera.id!));
			}
		});
	}

	replace(document: { config: unknown; app: unknown }): Promise<void> {
		return this.enqueue(() => this.persist(document));
	}

	saveAdvanced(target: 'config' | 'connections', value: unknown, revision: string): Promise<void> {
		return this.update((document) => {
			if (settingsRevision(document) !== revision)
				throw new ConfigurationError(
					'Settings changed since you opened the editor. Reload the saved settings before applying your changes.'
				);
			if (target === 'config') replaceDetectorConfig(document, value);
			else replaceConnections(document, value);
		});
	}

	saveDetector(input: v.InferOutput<typeof detectorInput>): Promise<void> {
		return this.update((document) => saveDetector(document, input));
	}

	deleteDetector(label: string): Promise<void> {
		return this.update((document) => deleteDetector(document, label));
	}

	saveStream(input: v.InferOutput<typeof streamInput>): Promise<void> {
		return this.update((document) => saveStream(document, input));
	}

	deleteStream(source: string): Promise<void> {
		return this.update((document) => deleteStream(document, source));
	}

	reorderStream(index0: number, index1: number): Promise<void> {
		return this.update((document) => reorderStream(document, index0, index1));
	}

	saveTelegram(input: v.InferOutput<typeof telegramInput>): Promise<void> {
		return this.update((document) => saveTelegram(document, input));
	}

	deleteTelegram(label: string): Promise<void> {
		return this.update((document) => deleteTelegram(document, label));
	}
}

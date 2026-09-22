import type * as v from 'valibot';
import { isDeepStrictEqual } from 'node:util';
import { DEFAULT_SCHEMA_URL, type Config, type Configuration } from '../../schema.ts';
import { readJson, writeJson } from '../json-file.ts';
import {
	ConfigurationError,
	detectorInput,
	normalizeConfig,
	normalizeConfiguration,
	sameTelegram,
	streamInput,
	telegramInput
} from '../../configuration.ts';
import { alertsInput, cameraInput } from '../../configuration.ts';
import { identifyCameras, saveCamera, removeCamera, saveAlerts } from './cameras.ts';
import { writeConfiguration } from './files.ts';
import { recordArchiveCheck, skipCameraAlerts, finishCameraSetup } from './camera-setup.ts';

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
		return identifyCameras(normalizeConfiguration(config, app));
	}

	read(): Promise<Configuration> {
		return this.enqueue(() => this.load());
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

	recordArchiveCheck(id: string, signature: string, verifiedAt: string): Promise<void> {
		return this.update((document) => recordArchiveCheck(document, id, signature, verifiedAt));
	}

	skipCameraAlerts(id: string): Promise<void> {
		return this.update((document) => skipCameraAlerts(document, id));
	}

	finishCameraSetup(id: string, monitoring: () => Promise<boolean>): Promise<void> {
		return this.update(async (document) => finishCameraSetup(document, id, await monitoring()));
	}

	replace(document: { config: unknown; app: unknown }): Promise<void> {
		return this.enqueue(() => this.persist(document));
	}

	saveDetector(input: v.InferOutput<typeof detectorInput>): Promise<void> {
		return this.update(({ config, app }) => {
			const index = input.original
				? app.detectors.findIndex((item) => item.label === input.original)
				: -1;
			if (input.original && index < 0)
				throw new ConfigurationError('This detector no longer exists.');
			if (app.detectors.some((item, i) => i !== index && item.label === input.meta.label)) {
				throw new ConfigurationError('A detector with this name already exists.');
			}
			const normalized = normalizeConfiguration({ detectors: [input.detector] }, {}).config
				.detectors[0];
			if (index < 0) {
				config.detectors.push(normalized);
				app.detectors.push(input.meta);
			} else {
				const meta = { ...app.detectors[index], ...input.meta };
				if (
					!isDeepStrictEqual(
						{ ...config.detectors[index], exporters: undefined },
						{ ...normalized, exporters: undefined }
					)
				)
					delete meta.preset;
				config.detectors[index] = normalized;
				app.detectors[index] = meta;
			}
		});
	}

	deleteDetector(label: string): Promise<void> {
		return this.update(({ config, app }) => {
			const index = app.detectors.findIndex((item) => item.label === label);
			if (index < 0) throw new ConfigurationError('This detector no longer exists.');
			config.detectors.splice(index, 1);
			app.detectors.splice(index, 1);
		});
	}

	saveStream(input: v.InferOutput<typeof streamInput>): Promise<void> {
		return this.update(({ config, app }) => {
			const index = input.original
				? app.streams.findIndex((item) => item.source === input.original)
				: -1;
			if (input.original && index < 0)
				throw new ConfigurationError('This camera source no longer exists.');
			if (app.streams.some((item, i) => i !== index && item.source === input.source)) {
				throw new ConfigurationError('This camera source already exists.');
			}
			const stream = { ...app.streams[index], label: input.label, source: input.source };
			if (input.original !== input.source) {
				stream.setup = stream.setup?.alerts ? { alerts: stream.setup.alerts } : undefined;
				delete stream.connection;
			}
			if (index < 0) app.streams.push(stream);
			else app.streams[index] = stream;
			for (const detector of config.detectors) {
				detector.detection.source = detector.detection.source.map((source) =>
					source === input.original ? input.source : source
				);
			}
		});
	}

	deleteStream(source: string): Promise<void> {
		return this.update(({ config, app }) => {
			if (!app.streams.some((item) => item.source === source))
				throw new ConfigurationError('This camera source no longer exists.');
			if (
				config.detectors.some(
					(item) => item.detection.source.length === 1 && item.detection.source[0] === source
				)
			) {
				throw new ConfigurationError(
					'This camera is a detector’s only source. Update or remove that detector first.'
				);
			}
			app.streams = app.streams.filter((item) => item.source !== source);
			for (const detector of config.detectors)
				detector.detection.source = detector.detection.source.filter((item) => item !== source);
		});
	}

	reorderStream(index0: number, index1: number): Promise<void> {
		return this.update(({ app }) => {
			if (
				![index0, index1].every(
					(index) => Number.isInteger(index) && index >= 0 && index < app.streams.length
				)
			) {
				throw new ConfigurationError('The camera order changed. Reload and try again.');
			}
			const [stream] = app.streams.splice(index0, 1);
			app.streams.splice(index1, 0, stream);
		});
	}

	saveTelegram(input: v.InferOutput<typeof telegramInput>): Promise<void> {
		return this.update(({ config, app }) => {
			const index = input.original
				? app.telegrams.findIndex((item) => item.label === input.original)
				: -1;
			if (input.original && index < 0)
				throw new ConfigurationError('This notification channel no longer exists.');
			if (
				app.telegrams.some(
					(item, i) => i !== index && (item.label === input.label || sameTelegram(item, input))
				)
			) {
				throw new ConfigurationError('This notification channel or name already exists.');
			}
			const previous = app.telegrams[index];
			const telegram = { label: input.label, token: input.token, chat: input.chat };
			if (index < 0) app.telegrams.push(telegram);
			else app.telegrams[index] = telegram;
			if (previous) {
				for (const detector of config.detectors) {
					for (const exporter of detector.exporters?.telegram ?? []) {
						if (sameTelegram(exporter, previous))
							Object.assign(exporter, { token: input.token, chat: input.chat });
					}
				}
			}
		});
	}

	deleteTelegram(label: string): Promise<void> {
		return this.update(({ config, app }) => {
			const telegram = app.telegrams.find((item) => item.label === label);
			if (!telegram) throw new ConfigurationError('This notification channel no longer exists.');
			app.telegrams = app.telegrams.filter((item) => item !== telegram);
			for (const detector of config.detectors) {
				if (detector.exporters?.telegram)
					detector.exporters.telegram = detector.exporters.telegram.filter(
						(item) => !sameTelegram(item, telegram)
					);
			}
		});
	}
}

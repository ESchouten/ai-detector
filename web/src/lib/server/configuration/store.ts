import type * as v from 'valibot';
import { isDeepStrictEqual } from 'node:util';
import type {
	Config,
	Configuration,
	DetectorPreset,
	LlmConnection,
	PairedDevice
} from '../../schema.ts';
import type { Locale } from '../../locales.ts';
import { serialQueue } from '../serial.ts';
import {
	alertsInput,
	ConfigurationError,
	cameraInput,
	detectorInput,
	normalizeConfig,
	normalizeConfiguration,
	telegramInput,
	heartbeatInput
} from '../../configuration.ts';
import { identifyCameras, saveCamera, removeCamera } from './cameras.ts';
import { SettingsFiles, type SettingsPaths } from './settings-files.ts';
import { saveDetector, deleteDetector } from './detectors.ts';
import { saveTelegram, deleteTelegram, saveAlerts } from './telegrams.ts';
import { saveLlm, deleteLlm } from './llms.ts';
import { replaceConnections, replaceDetectorConfig, settingsRevision } from './advanced.ts';
import { recordArchiveCheck, finishCameraSetup } from './camera-setup.ts';
import { followPresets, forgetChangedPresets } from './followed-presets.ts';

interface Runtime {
	validate(config: Config): Promise<void>;
	apply(): Promise<void>;
	stop(): Promise<void>;
	fail(error: unknown): void;
}

/** Where the store learns the interface language, and who it tells about the saved one. */
export interface LanguageSource {
	/** The language the browser being answered asked for, when it stated one we have. */
	requested(): Locale | undefined;
	/** Told whenever settings are read or written, so work outside a request uses it too. */
	saved(language: Locale | undefined): void;
}

/**
 * The settings of this installation and everything that may change them. Changes run one at a
 * time: read, change, check with the detector, save, then apply to the running detector.
 */
export class ConfigurationStore {
	private readonly enqueue = serialQueue();
	private readonly files: SettingsFiles;
	private runtime: () => Runtime | null;
	private language?: LanguageSource;

	constructor(
		files: SettingsPaths,
		runtime: () => Runtime | null = () => null,
		language?: LanguageSource
	) {
		this.files = new SettingsFiles(files);
		this.runtime = runtime;
		this.language = language;
	}

	private async load(): Promise<Configuration> {
		const document = await this.files.load();
		this.language?.saved(document.app.language);
		return document;
	}

	private async save(document: Configuration, config = true): Promise<void> {
		await this.files.write(document, config);
		this.language?.saved(document.app.language);
	}

	/**
	 * An installation takes the language of the browser that first saves settings in it, so
	 * setup needs no language question; `saveLanguage` changes it afterwards.
	 */
	private keepLanguage(app: Configuration['app'], current?: Locale): void {
		const language = app.language ?? current ?? this.language?.requested();
		if (language) app.language = language;
	}

	async recoveryAvailable(): Promise<boolean> {
		return (await this.files.lastValid()) !== null;
	}

	restore(): Promise<void> {
		return this.enqueue(async () => {
			const saved = await this.files.lastValid();
			if (!saved) throw new ConfigurationError('No previous valid settings are available.');
			const document = identifyCameras(saved);
			// Recover settings without restoring access for a previously revoked browser.
			const devices = await this.files.recoverableDevices();
			if (devices) document.app.devices = devices;
			else delete document.app.devices;
			if (document.config.detectors.length) await this.runtime()?.validate(document.config);
			await this.files.setAside();
			await this.save(document);
			await this.applySaved(document.config);
		});
	}

	read(): Promise<Configuration> {
		return this.enqueue(() => this.load());
	}

	/** Not queued: atomic file writes make committed access readable during slow runtime changes. */
	async readDevices(): Promise<PairedDevice[]> {
		return (await this.files.devices()) ?? [];
	}

	updateDevices(change: (devices: PairedDevice[]) => PairedDevice[]): Promise<void> {
		return this.enqueue(() => this.files.updateDevices(change));
	}

	/** Seed onboarding without starting monitoring or sending alerts. */
	initialize(
		document: Configuration,
		publishFiles: () => Promise<void>,
		resuming = false
	): Promise<void> {
		return this.enqueue(async () => {
			const next = forgetChangedPresets(
				identifyCameras(normalizeConfiguration(document.config, document.app))
			);
			const current = await this.load();
			if (current.app.devices) next.app.devices = current.app.devices;
			else delete next.app.devices;
			this.keepLanguage(next.app, current.app.language);
			if (resuming && isDeepStrictEqual(current, next)) return;
			const recoveringApp = resuming && isDeepStrictEqual(await this.files.savedApp(), next.app);
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
			await this.save(next);
			await this.files.remember(next);
		});
	}

	private async persist(input: { config: unknown; app: unknown }): Promise<void> {
		const { config, app } = identifyCameras(normalizeConfiguration(input.config, input.app));
		app.devices = await this.files.devices();
		this.keepLanguage(app);
		const previous = await this.files.savedConfig();
		const configChanged =
			previous === null || !isDeepStrictEqual(normalizeConfig(previous), config);
		const runtime = this.runtime();
		if (configChanged && config.detectors.length) await runtime?.validate(config);
		if (!configChanged) {
			await this.save({ config, app }, false);
			await this.files.remember({ config, app });
			return;
		}
		await this.save({ config, app });
		await this.files.remember({ config, app });
		await this.applySaved(config);
	}

	private async applySaved(config: Config): Promise<void> {
		const runtime = this.runtime();
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

	saveLanguage(language: Locale): Promise<void> {
		return this.update((document) => {
			document.app.language = language;
		});
	}

	/** Turn the detector's heartbeat on, change it, or turn it off with `null`. */
	saveHeartbeat(input: v.InferOutput<typeof heartbeatInput>): Promise<void> {
		return this.update((document) => {
			if (input) document.config.health = { ...document.config.health, ...input };
			else delete document.config.health;
		});
	}

	saveDetector(input: v.InferOutput<typeof detectorInput>): Promise<void> {
		return this.update((document) => saveDetector(document, input));
	}

	/**
	 * Bring detectors that follow a preset up to date with it, and name the ones that changed.
	 * Nothing is written when all of them already are.
	 */
	followPresets(presets: DetectorPreset[]): Promise<string[]> {
		return this.enqueue(async () => {
			const document = await this.load();
			const updated = followPresets(document, presets);
			if (updated.length) await this.persist(document);
			return updated;
		});
	}

	deleteDetector(label: string): Promise<void> {
		return this.update((document) => deleteDetector(document, label));
	}

	saveTelegram(input: v.InferOutput<typeof telegramInput>): Promise<void> {
		return this.update((document) => saveTelegram(document, input));
	}

	deleteTelegram(label: string): Promise<void> {
		return this.update((document) => deleteTelegram(document, label));
	}
}

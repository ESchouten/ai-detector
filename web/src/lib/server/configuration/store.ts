import * as v from 'valibot';
import { isDeepStrictEqual } from 'node:util';
import { chmod, copyFile, rm } from 'node:fs/promises';
import {
	DEFAULT_SCHEMA_URL,
	appSchema,
	type Config,
	type Configuration,
	type LlmConnection,
	type PairedDevice
} from '../../schema.ts';
import type { Locale } from '../../locales.ts';
import { readJson, writeJson } from '../json-file.ts';
import { serialQueue } from '../serial.ts';
import { webLog } from '../web-log.ts';
import { exclusiveWrite, monitoringEnabled, setMonitoringEnabled } from '../monitoring-flag.ts';
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
import { writeConfiguration } from './files.ts';
import { upgradeLauncherSettings, upgradeVerificationKeys } from './upgrade.ts';
import { saveDetector, deleteDetector } from './detectors.ts';
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

/** Where the store learns the interface language, and who it tells about the saved one. */
export interface LanguageSource {
	/** The language the browser being answered asked for, when it stated one we have. */
	requested(): Locale | undefined;
	/** Told whenever settings are read or written, so work outside a request uses it too. */
	saved(language: Locale | undefined): void;
}

const missingFile = Symbol('missing settings file');
type RecoverySettings = { config: Config; app?: Configuration['app'] };

export class ConfigurationStore {
	private readonly enqueue = serialQueue();
	private files: { config: string; app: string; runtime?: string };
	private runtime: () => Runtime | null;
	private recoveryRevision = '';
	private launcherSettingsUpgraded = false;
	private language?: LanguageSource;

	/** `files.runtime` is the runtime.json of earlier versions, read once to move its settings. */
	constructor(
		files: { config: string; app: string; runtime?: string },
		runtime: () => Runtime | null = () => null,
		language?: LanguageSource
	) {
		this.files = files;
		this.runtime = runtime;
		this.language = language;
	}

	private async load(): Promise<Configuration> {
		const [config, app] = await Promise.all([
			readJson<unknown>(this.files.config, missingFile),
			readJson<unknown>(this.files.app, missingFile)
		]);
		if (config === missingFile || app === missingFile) {
			const saved = await readJson<RecoverySettings>(`${this.files.config}.last-valid`);
			if (saved && (config === missingFile || saved.app !== undefined))
				throw new ConfigurationError(
					'A settings file is missing. Restore the last valid settings to continue.'
				);
		}
		try {
			const input =
				config === missingFile ? { $schema: DEFAULT_SCHEMA_URL, detectors: [] } : config;
			const legacy = await this.legacyLauncherSettings(config);
			const upgraded = upgradeVerificationKeys(legacy ? legacy.config : input);
			const document = identifyCameras(
				normalizeConfiguration(upgraded, app === missingFile ? {} : app)
			);
			if (upgraded !== input) await this.write(document);
			await this.retireLauncherSettings(legacy);
			if (config !== missingFile)
				await this.remember(document, app !== missingFile || upgraded !== input);
			this.language?.saved(document.app.language);
			return document;
		} catch (error) {
			if (error instanceof ConfigurationError)
				throw new ConfigurationError(`${this.files.config}: ${error.message}`, { cause: error });
			throw error;
		}
	}

	/**
	 * Settings an earlier version kept in runtime.json. Looked for once per process, and never
	 * for a new installation: reading settings must not create them.
	 */
	private async legacyLauncherSettings(config: unknown) {
		if (config === missingFile || this.launcherSettingsUpgraded || !this.files.runtime) return;
		// A damaged leftover must not make the real settings unreadable.
		const saved = await readJson<unknown>(this.files.runtime).catch(() => null);
		return upgradeLauncherSettings(config, saved);
	}

	/** Remove runtime.json only after its values are safely in the two settings files. */
	private async retireLauncherSettings(legacy?: { enabled: boolean }): Promise<void> {
		if (legacy) {
			if (legacy.enabled) await setMonitoringEnabled(this.files.app, true);
			await rm(this.files.runtime!, { force: true });
		}
		this.launcherSettingsUpgraded = true;
	}

	/**
	 * Replace app.json, and config.json unless only metadata changed. The launcher's `monitoring`
	 * flag is not part of these documents; whatever app.json holds at this moment is kept.
	 */
	private write(document: Configuration, config = true): Promise<void> {
		return exclusiveWrite(this.files.app, async () => {
			// Unreadable settings are being replaced; a running launcher writes its flag again.
			const resumes = await monitoringEnabled(this.files.app).catch(() => false);
			const app = resumes ? { ...document.app, monitoring: true } : document.app;
			if (config) await writeConfiguration(this.files, { config: document.config, app });
			else await writeJson(this.files.app, app);
			this.language?.saved(document.app.language);
		});
	}

	/**
	 * An installation takes the language of the browser that first saves settings in it, so
	 * setup needs no language question; `saveLanguage` changes it afterwards.
	 */
	private keepLanguage(app: Configuration['app'], current?: Locale): void {
		const language = app.language ?? current ?? this.language?.requested();
		if (language) app.language = language;
	}

	private async remember(document: Configuration, appPresent = true): Promise<void> {
		const revision = `${appPresent}:${settingsRevision(document)}`;
		if (revision === this.recoveryRevision) return;
		try {
			await writeJson(`${this.files.config}.last-valid`, {
				...document,
				app: appPresent ? { ...document.app, devices: undefined } : undefined
			});
			this.recoveryRevision = revision;
		} catch (error) {
			// Read-only or full storage must not make valid settings unreadable.
			webLog.error('Could not save the settings recovery snapshot', error);
		}
	}

	async recoveryAvailable(): Promise<boolean> {
		const saved = await readJson<RecoverySettings>(`${this.files.config}.last-valid`);
		if (!saved) return false;
		normalizeConfiguration(saved.config, saved.app === undefined ? {} : saved.app);
		return true;
	}

	restore(): Promise<void> {
		return this.enqueue(async () => {
			const saved = await readJson<RecoverySettings>(`${this.files.config}.last-valid`);
			if (!saved) throw new ConfigurationError('No previous valid settings are available.');
			const document = identifyCameras(
				normalizeConfiguration(saved.config, saved.app === undefined ? {} : saved.app)
			);
			// Recover settings without restoring access for a previously revoked browser.
			try {
				document.app.devices = (await this.loadDeviceSettings()).devices;
			} catch (error) {
				if (!(error instanceof SyntaxError || error instanceof v.ValiError)) throw error;
				delete document.app.devices;
				webLog.warn('Connected devices could not be recovered; pair remote browsers again.', error);
			}
			if (document.config.detectors.length) await this.runtime()?.validate(document.config);
			const stamp = new Date().toISOString().replaceAll(':', '-');
			for (const file of [this.files.config, this.files.app]) {
				try {
					const backup = `${file}.${stamp}.invalid`;
					await copyFile(file, backup);
					await chmod(backup, 0o600);
				} catch (error) {
					if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
				}
			}
			await this.write(document);
			await this.applySaved(document.config);
		});
	}

	read(): Promise<Configuration> {
		return this.enqueue(() => this.load());
	}

	private async loadDeviceSettings() {
		// Access to diagnostics and recovery must not depend on valid detector settings.
		return v.parse(
			v.looseObject({ devices: appSchema.entries.devices }),
			await readJson(this.files.app, {})
		);
	}

	async readDevices(): Promise<PairedDevice[]> {
		// Atomic file writes make committed access readable during slow runtime changes.
		return (await this.loadDeviceSettings()).devices ?? [];
	}

	updateDevices(change: (devices: PairedDevice[]) => PairedDevice[]): Promise<void> {
		return this.enqueue(() =>
			exclusiveWrite(this.files.app, async () => {
				const app = await this.loadDeviceSettings();
				app.devices = change(app.devices ?? []);
				await writeJson(this.files.app, app);
			})
		);
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
			if (current.app.devices) next.app.devices = current.app.devices;
			else delete next.app.devices;
			this.keepLanguage(next.app, current.app.language);
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
			await this.write(next);
			await this.remember(next);
		});
	}

	private async persist(input: { config: unknown; app: unknown }): Promise<void> {
		const { config, app } = identifyCameras(normalizeConfiguration(input.config, input.app));
		app.devices = (await this.loadDeviceSettings()).devices;
		this.keepLanguage(app);
		const previous = await readJson<unknown>(this.files.config);
		const configChanged =
			previous === null || !isDeepStrictEqual(normalizeConfig(previous), config);
		const runtime = this.runtime();
		if (configChanged && config.detectors.length) await runtime?.validate(config);
		if (!configChanged) {
			await this.write({ config, app }, false);
			await this.remember({ config, app });
			return;
		}
		await this.write({ config, app });
		await this.remember({ config, app });
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

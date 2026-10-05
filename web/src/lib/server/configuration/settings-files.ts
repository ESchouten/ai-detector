import { chmod, copyFile, rm } from 'node:fs/promises';
import * as v from 'valibot';
import { ConfigurationError, normalizeConfiguration } from '../../configuration.ts';
import {
	DEFAULT_SCHEMA_URL,
	appSchema,
	type Config,
	type Configuration,
	type PairedDevice
} from '../../schema.ts';
import { readJson, writeJson } from '../json-file.ts';
import { exclusiveWrite, monitoringEnabled, setMonitoringEnabled } from '../monitoring-flag.ts';
import { webLog } from '../web-log.ts';
import { settingsRevision } from './advanced.ts';
import { identifyCameras } from './cameras.ts';
import { writeConfiguration } from './files.ts';
import { upgradeLauncherSettings, upgradeVerificationKeys } from './upgrade.ts';

export interface SettingsPaths {
	config: string;
	app: string;
	/** The runtime.json of earlier versions, read once to move its settings. */
	runtime?: string;
}

const missingFile = Symbol('missing settings file');
type RecoverySettings = { config: Config; app?: Configuration['app'] };

/**
 * The settings as they are kept on disk: config.json for the detector, app.json for this
 * application, the snapshot of the last valid pair, and what earlier versions left behind.
 * The settings store decides what is saved and when, one operation at a time.
 */
export class SettingsFiles {
	private readonly paths: SettingsPaths;
	private readonly snapshot: string;
	private recoveryRevision = '';
	private launcherSettingsUpgraded = false;

	constructor(paths: SettingsPaths) {
		this.paths = paths;
		this.snapshot = `${paths.config}.last-valid`;
	}

	/**
	 * Both files as one valid document. Settings of earlier versions are moved to their current
	 * place, and a valid document becomes the snapshot to recover from.
	 */
	async load(): Promise<Configuration> {
		const [config, app] = await Promise.all([
			readJson<unknown>(this.paths.config, missingFile),
			readJson<unknown>(this.paths.app, missingFile)
		]);
		if (config === missingFile || app === missingFile) {
			const saved = await readJson<RecoverySettings>(this.snapshot);
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
			return document;
		} catch (error) {
			if (error instanceof ConfigurationError)
				throw new ConfigurationError(`${this.paths.config}: ${error.message}`, { cause: error });
			throw error;
		}
	}

	/**
	 * Settings an earlier version kept in runtime.json. Looked for once per process, and never
	 * for a new installation: reading settings must not create them.
	 */
	private async legacyLauncherSettings(config: unknown) {
		if (config === missingFile || this.launcherSettingsUpgraded || !this.paths.runtime) return;
		// A damaged leftover must not make the real settings unreadable.
		const saved = await readJson<unknown>(this.paths.runtime).catch(() => null);
		return upgradeLauncherSettings(config, saved);
	}

	/** Remove runtime.json only after its values are safely in the two settings files. */
	private async retireLauncherSettings(legacy?: { enabled: boolean }): Promise<void> {
		if (legacy) {
			if (legacy.enabled) await setMonitoringEnabled(this.paths.app, true);
			await rm(this.paths.runtime!, { force: true });
		}
		this.launcherSettingsUpgraded = true;
	}

	/**
	 * Replace app.json, and config.json unless only metadata changed. The launcher's `monitoring`
	 * flag is not part of these documents; whatever app.json holds at this moment is kept.
	 */
	write(document: Configuration, config = true): Promise<void> {
		return exclusiveWrite(this.paths.app, async () => {
			// Unreadable settings are being replaced; a running launcher writes its flag again.
			const resumes = await monitoringEnabled(this.paths.app).catch(() => false);
			const app = resumes ? { ...document.app, monitoring: true } : document.app;
			if (config) await writeConfiguration(this.paths, { config: document.config, app });
			else await writeJson(this.paths.app, app);
		});
	}

	/** Keep a valid document as the snapshot to recover from, without its paired devices. */
	async remember(document: Configuration, appPresent = true): Promise<void> {
		const revision = `${appPresent}:${settingsRevision(document)}`;
		if (revision === this.recoveryRevision) return;
		try {
			await writeJson(this.snapshot, {
				...document,
				app: appPresent ? { ...document.app, devices: undefined } : undefined
			});
			this.recoveryRevision = revision;
		} catch (error) {
			// Read-only or full storage must not make valid settings unreadable.
			webLog.error('Could not save the settings recovery snapshot', error);
		}
	}

	/** The snapshot of the last valid settings, if there is one. A damaged snapshot is an error. */
	async lastValid(): Promise<Configuration | null> {
		const saved = await readJson<RecoverySettings>(this.snapshot);
		return saved
			? normalizeConfiguration(saved.config, saved.app === undefined ? {} : saved.app)
			: null;
	}

	/** Copy the present files aside before recovery replaces them. */
	async setAside(): Promise<void> {
		const stamp = new Date().toISOString().replaceAll(':', '-');
		for (const file of [this.paths.config, this.paths.app]) {
			try {
				const backup = `${file}.${stamp}.invalid`;
				await copyFile(file, backup);
				await chmod(backup, 0o600);
			} catch (error) {
				if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
			}
		}
	}

	/** config.json exactly as saved, or null without one. */
	savedConfig(): Promise<unknown> {
		return readJson<unknown>(this.paths.config);
	}

	/** app.json exactly as saved, or null without one. */
	savedApp(): Promise<unknown> {
		return readJson<unknown>(this.paths.app);
	}

	private async deviceSettings() {
		// Access to diagnostics and recovery must not depend on valid detector settings.
		return v.parse(
			v.looseObject({ devices: appSchema.entries.devices }),
			await readJson(this.paths.app, {})
		);
	}

	/** The paired devices, read without looking at any other setting. */
	async devices(): Promise<PairedDevice[] | undefined> {
		return (await this.deviceSettings()).devices;
	}

	/** The paired devices for recovered settings; none, with a warning, when app.json is unreadable. */
	async recoverableDevices(): Promise<PairedDevice[] | undefined> {
		try {
			return await this.devices();
		} catch (error) {
			if (!(error instanceof SyntaxError || error instanceof v.ValiError)) throw error;
			webLog.warn('Connected devices could not be recovered; pair remote browsers again.', error);
			return undefined;
		}
	}

	updateDevices(change: (devices: PairedDevice[]) => PairedDevice[]): Promise<void> {
		return exclusiveWrite(this.paths.app, async () => {
			const app = await this.deviceSettings();
			app.devices = change(app.devices ?? []);
			await writeJson(this.paths.app, app);
		});
	}
}

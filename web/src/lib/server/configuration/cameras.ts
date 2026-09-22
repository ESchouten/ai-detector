import { createHash } from 'node:crypto';
import { isDeepStrictEqual } from 'node:util';
import type * as v from 'valibot';
import {
	ConfigurationError,
	sameTelegram,
	type alertsInput,
	type cameraInput
} from '../../configuration.ts';
import type {
	Configuration,
	DetectorConfig,
	DetectorMeta,
	StreamMeta,
	TelegramMeta
} from '../../schema.ts';
import { initialSetup } from './presets.ts';

export function identifyCameras(document: Configuration): Configuration {
	for (const stream of document.app.streams) {
		stream.id ??= createHash('sha256').update(stream.source).digest('hex');
	}
	if (new Set(document.app.streams.map((stream) => stream.id)).size !== document.app.streams.length)
		throw new ConfigurationError(
			'Camera identities are duplicated. Restore your camera settings from a backup.'
		);
	return document;
}

function availableLabel(document: Configuration, label: string): string {
	const used = new Set(document.app.detectors.map((item) => item.label));
	let value = label;
	for (let suffix = 2; used.has(value); suffix++) value = `${label} (${suffix})`;
	return value;
}

function detachCamera(document: Configuration, source: string): DetectorConfig[] {
	const detached: DetectorConfig[] = [];
	for (let index = document.config.detectors.length - 1; index >= 0; index--) {
		const detector = document.config.detectors[index];
		if (!detector.detection.source.includes(source)) continue;
		detached.push(structuredClone(detector));
		detector.detection.source = detector.detection.source.filter((item) => item !== source);
		if (!detector.detection.source.length) {
			document.config.detectors.splice(index, 1);
			document.app.detectors.splice(index, 1);
		}
	}
	return detached;
}

function preserveDeliverySettings(detector: DetectorConfig, previous: DetectorConfig[]): void {
	const exporters: NonNullable<DetectorConfig['exporters']> = {};
	for (const original of previous) {
		for (const [name, destinations] of Object.entries(original.exporters ?? {})) {
			const combined = [...(exporters[name] ?? []), ...(destinations ?? [])];
			exporters[name] = combined.filter(
				(item, index) => combined.findIndex((other) => isDeepStrictEqual(item, other)) === index
			);
		}
	}
	detector.exporters = { ...detector.exporters, ...exporters };
}

function monitoringToCopy(document: Configuration, id: string) {
	const camera = document.app.streams.find((stream) => stream.id === id);
	if (!camera)
		throw new ConfigurationError('The camera to copy no longer exists. Choose another camera.');
	const rules = document.config.detectors.flatMap((detector, index) =>
		detector.detection.source.includes(camera.source)
			? [{ detector, meta: document.app.detectors[index] }]
			: []
	);
	if (!rules.length)
		throw new ConfigurationError(
			'This camera is view only. Choose a monitored camera to copy, or choose View only.'
		);
	return structuredClone(rules);
}

function addCopiedMonitoring(
	document: Configuration,
	rules: ReturnType<typeof monitoringToCopy>,
	source: string,
	camera: DetectorMeta
): void {
	for (const { detector, meta } of rules) {
		detector.detection.source = [source];
		document.config.detectors.push(detector);
		document.app.detectors.push({
			...meta,
			...camera,
			label: availableLabel(
				document,
				rules.length === 1 ? camera.label : `${camera.label} — ${meta.label}`
			)
		});
	}
}

function updateCameraMetadata(
	camera: StreamMeta,
	input: v.InferOutput<typeof cameraInput>,
	pictureVerifiedAt?: string
): void {
	if (camera.source !== input.source) {
		camera.setup = camera.setup?.alerts ? { alerts: camera.setup.alerts } : undefined;
		delete camera.connection;
	}
	if (input.connection === null) delete camera.connection;
	else if (input.connection) camera.connection = input.connection;
	if (pictureVerifiedAt) camera.setup = { ...camera.setup, pictureVerifiedAt };
	if (camera.setup && input.preset !== 'keep') {
		delete camera.setup.archiveVerifiedAt;
		delete camera.setup.archiveSignature;
		delete camera.setup.completedAt;
		delete camera.setup.completionSignature;
	}
	Object.assign(camera, { label: input.label, source: input.source });
}

export function saveCamera(
	document: Configuration,
	input: v.InferOutput<typeof cameraInput>,
	pictureVerifiedAt?: string
) {
	const existing = input.id
		? document.app.streams.find((stream) => stream.id === input.id)
		: undefined;
	if (input.id && !existing) throw new ConfigurationError('This camera no longer exists.');
	if (document.app.streams.some((stream) => stream !== existing && stream.source === input.source))
		throw new ConfigurationError('This camera is already saved. Edit it from Cameras.');
	if (document.app.streams.some((stream) => stream !== existing && stream.label === input.label))
		throw new ConfigurationError('A camera with this name already exists. Choose another name.');
	if (!existing && input.preset === 'keep')
		throw new ConfigurationError('Choose what this camera should watch for.');
	const copiedRules =
		input.preset === 'copy' ? monitoringToCopy(document, input.copyFromCameraId) : [];
	const camera: StreamMeta = existing ?? { source: input.source };
	const previousSource = camera.source;
	updateCameraMetadata(camera, input, pictureVerifiedAt);
	if (!existing) document.app.streams.push(camera);
	identifyCameras(document);
	for (const detector of document.config.detectors)
		detector.detection.source = detector.detection.source.map((source) =>
			source === previousSource ? input.source : source
		);
	if (input.preset === 'copy') {
		addCopiedMonitoring(document, copiedRules, input.source, {
			label: input.label,
			cameraId: camera.id
		});
	} else if (input.preset !== 'keep') {
		const previous = detachCamera(document, input.source);
		if (input.preset !== 'view-only') {
			const detector = initialSetup({
				label: input.label,
				source: input.source,
				preset: input.preset
			}).config.detectors[0];
			preserveDeliverySettings(detector, previous);
			document.config.detectors.push(detector);
			document.app.detectors.push({
				label: availableLabel(document, input.label),
				cameraId: camera.id,
				preset: input.preset
			});
		}
	}
	return {
		id: camera.id!,
		monitored: document.config.detectors.some((detector) =>
			detector.detection.source.includes(input.source)
		)
	};
}

export function removeCamera(document: Configuration, id: string): void {
	const camera = document.app.streams.find((stream) => stream.id === id);
	if (!camera) throw new ConfigurationError('This camera no longer exists.');
	detachCamera(document, camera.source);
	document.app.streams = document.app.streams.filter((stream) => stream !== camera);
}

function setChannel(
	detector: DetectorConfig,
	channel: TelegramMeta,
	previous: TelegramMeta | undefined,
	enabled: boolean
): void {
	const channels = detector.exporters?.telegram ?? [];
	const existing = channels.find((item) => sameTelegram(item, previous ?? channel));
	const others = channels.filter((item) => !sameTelegram(item, previous ?? channel));
	detector.exporters ??= {};
	detector.exporters.telegram = enabled
		? [...others, { ...existing, token: channel.token, chat: channel.chat }]
		: others;
}

function alertRecipientToUpdate(document: Configuration, input: v.InferOutput<typeof alertsInput>) {
	const previous = input.original
		? document.app.telegrams.find((item) => item.label === input.original)
		: undefined;
	if (input.original && !previous)
		throw new ConfigurationError('This alert recipient no longer exists.');
	if (!input.received && (!previous || !sameTelegram(previous, input)))
		throw new ConfigurationError(
			'Confirm that you received the test alert before enabling new or changed connection details.'
		);
	if (
		document.app.telegrams.some(
			(item) => item !== previous && (item.label === input.label || sameTelegram(item, input))
		)
	)
		throw new ConfigurationError('This alert recipient or name already exists.');
	return previous;
}

export function saveAlerts(
	document: Configuration,
	input: v.InferOutput<typeof alertsInput>
): void {
	const previous = alertRecipientToUpdate(document, input);
	const selected = document.app.streams.filter((stream) => input.cameraIds.includes(stream.id!));
	if (selected.length !== new Set(input.cameraIds).size)
		throw new ConfigurationError('A selected camera no longer exists.');
	if (!selected.length)
		throw new ConfigurationError('Choose at least one monitored camera for these alerts.');
	for (const camera of selected) {
		if (
			!document.config.detectors.some((detector) =>
				detector.detection.source.includes(camera.source)
			)
		)
			throw new ConfigurationError(
				`${camera.label ?? 'This camera'} is view only. Enable monitoring before adding alerts.`
			);
	}
	const channel = { label: input.label, token: input.token, chat: input.chat };
	const selectedSources = new Set(selected.map((camera) => camera.source));
	const previousRules = document.config.detectors.filter(
		(detector) =>
			previous && detector.exporters?.telegram?.some((item) => sameTelegram(item, previous))
	);
	const previouslySelectedSources = new Set(
		previousRules.flatMap((detector) => detector.detection.source)
	);
	const additions: { detector: DetectorConfig; meta: DetectorMeta }[] = [];
	for (const [index, detector] of document.config.detectors.entries()) {
		const watched = detector.detection.source.filter(
			(source) =>
				selectedSources.has(source) &&
				(!previouslySelectedSources.has(source) || previousRules.includes(detector))
		);
		if (watched.length && watched.length !== detector.detection.source.length) {
			const split = structuredClone(detector);
			split.detection.source = watched;
			detector.detection.source = detector.detection.source.filter(
				(source) => !watched.includes(source)
			);
			setChannel(split, channel, previous, true);
			additions.push({
				detector: split,
				meta: {
					...document.app.detectors[index],
					label: availableLabel(document, `${document.app.detectors[index].label} — ${input.label}`)
				}
			});
			setChannel(detector, channel, previous, false);
		} else setChannel(detector, channel, previous, watched.length > 0);
	}
	for (const item of additions) {
		document.config.detectors.push(item.detector);
		document.app.detectors.push(item.meta);
	}
	if (previous) Object.assign(previous, channel);
	else document.app.telegrams.push(channel);
}

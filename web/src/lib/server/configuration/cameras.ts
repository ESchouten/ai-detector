import { createHash } from 'node:crypto';
import { isDeepStrictEqual } from 'node:util';
import type * as v from 'valibot';
import { ConfigurationError, type cameraInput } from '../../configuration.ts';
import type {
	Configuration,
	DetectorConfig,
	DetectorMeta,
	DetectorPreset,
	StreamMeta
} from '../../schema.ts';

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
	const exporters: Record<string, unknown[]> = {};
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
	if (camera.setup && input.mode !== 'keep') {
		delete camera.setup.archiveVerifiedAt;
		delete camera.setup.archiveSignature;
		delete camera.setup.completedAt;
		delete camera.setup.completionSignature;
	}
	Object.assign(camera, { label: input.label, source: input.source });
}

function monitoringForCamera(input: v.InferOutput<typeof cameraInput>, preset?: DetectorPreset) {
	if (input.mode !== 'preset') return;
	if (!preset || preset.id !== input.preset)
		throw new ConfigurationError(
			'This monitoring preset is no longer available. Choose another preset, or keep the current monitoring settings.'
		);
	const detector = structuredClone(preset.detector);
	detector.detection.source = [input.source];
	return { id: preset.id, detector };
}

export function saveCamera(
	document: Configuration,
	input: v.InferOutput<typeof cameraInput>,
	preset?: DetectorPreset,
	pictureVerifiedAt?: string
) {
	const monitoring = monitoringForCamera(input, preset);
	const existing = input.id
		? document.app.streams.find((stream) => stream.id === input.id)
		: undefined;
	if (input.id && !existing) throw new ConfigurationError('This camera no longer exists.');
	if (document.app.streams.some((stream) => stream !== existing && stream.source === input.source))
		throw new ConfigurationError('This camera is already saved. Edit it from Cameras.');
	if (document.app.streams.some((stream) => stream !== existing && stream.label === input.label))
		throw new ConfigurationError('A camera with this name already exists. Choose another name.');
	if (!existing && input.mode === 'keep')
		throw new ConfigurationError('Choose what this camera should watch for.');
	const copiedRules =
		input.mode === 'copy' ? monitoringToCopy(document, input.copyFromCameraId) : [];
	const camera: StreamMeta = existing ?? { source: input.source };
	const previousSource = camera.source;
	updateCameraMetadata(camera, input, pictureVerifiedAt);
	if (!existing) document.app.streams.push(camera);
	identifyCameras(document);
	for (const detector of document.config.detectors)
		detector.detection.source = detector.detection.source.map((source) =>
			source === previousSource ? input.source : source
		);
	if (input.mode === 'copy') {
		addCopiedMonitoring(document, copiedRules, input.source, {
			label: input.label,
			cameraId: camera.id
		});
	} else if (input.mode !== 'keep') {
		const previous = detachCamera(document, input.source);
		if (monitoring) {
			const detector = monitoring.detector;
			preserveDeliverySettings(detector, previous);
			document.config.detectors.push(detector);
			document.app.detectors.push({
				label: availableLabel(document, input.label),
				cameraId: camera.id,
				preset: monitoring.id
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

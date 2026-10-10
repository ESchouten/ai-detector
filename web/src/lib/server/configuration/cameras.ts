import { createHash } from 'node:crypto';
import type * as v from 'valibot';
import { ConfigurationError, type cameraInput } from '../../configuration.ts';
import type { Configuration, StreamMeta } from '../../schema.ts';

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

function detachCamera(document: Configuration, source: string): void {
	for (let index = document.config.detectors.length - 1; index >= 0; index--) {
		const detector = document.config.detectors[index];
		if (!detector.detection.source.includes(source)) continue;
		detector.detection.source = detector.detection.source.filter((item) => item !== source);
		if (!detector.detection.source.length) {
			document.config.detectors.splice(index, 1);
			document.app.detectors.splice(index, 1);
		}
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
	const camera: StreamMeta = existing ?? { source: input.source };
	const previousSource = camera.source;
	updateCameraMetadata(camera, input, pictureVerifiedAt);
	if (!existing) document.app.streams.push(camera);
	identifyCameras(document);
	for (const detector of document.config.detectors)
		detector.detection.source = detector.detection.source.map((source) =>
			source === previousSource ? input.source : source
		);
	return { id: camera.id! };
}

export function removeCamera(document: Configuration, id: string): void {
	const camera = document.app.streams.find((stream) => stream.id === id);
	if (!camera) throw new ConfigurationError('This camera no longer exists.');
	detachCamera(document, camera.source);
	document.app.streams = document.app.streams.filter((stream) => stream !== camera);
}

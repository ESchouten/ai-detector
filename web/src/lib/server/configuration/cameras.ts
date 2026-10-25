import { createHash } from 'node:crypto';
import type * as v from 'valibot';
import { ConfigurationError, type cameraInput } from '../../configuration.ts';
import type {
	Camera,
	CameraDevice,
	Configuration,
	LoadedConfiguration,
	StreamMeta
} from '../../schema.ts';
import { movedSource } from '../cameras/connection.ts';
import type { CameraMove } from '../cameras/identity.ts';
import { keepCameraSetup } from './camera-setup.ts';

/** A camera's id comes from its first address and stays when the address changes. */
function cameraId(source: string): string {
	return createHash('sha256').update(source).digest('hex');
}

export function identifyCameras(document: Configuration): LoadedConfiguration {
	for (const stream of document.app.streams) stream.id ??= cameraId(stream.source);
	if (new Set(document.app.streams.map((stream) => stream.id)).size !== document.app.streams.length)
		throw new ConfigurationError(
			'Camera identities are duplicated. Restore your camera settings from a backup.'
		);
	return document as LoadedConfiguration;
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
		delete camera.setup;
		delete camera.connection;
		// Another address can be another camera.
		delete camera.device;
	}
	if (input.connection === null) delete camera.connection;
	else if (input.connection) camera.connection = input.connection;
	if (pictureVerifiedAt) camera.setup = { ...camera.setup, pictureVerifiedAt };
	Object.assign(camera, { label: input.label, source: input.source });
}

export function saveCamera(
	document: LoadedConfiguration,
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
	const camera: Camera = existing ?? { id: cameraId(input.source), source: input.source };
	const previousSource = camera.source;
	updateCameraMetadata(camera, input, pictureVerifiedAt);
	if (!existing) document.app.streams.push(camera);
	for (const detector of document.config.detectors)
		detector.detection.source = detector.detection.source.map((source) =>
			source === previousSource ? input.source : source
		);
	return { id: camera.id };
}

export function removeCamera(document: Configuration, id: string): void {
	const camera = document.app.streams.find((stream) => stream.id === id);
	if (!camera) throw new ConfigurationError('This camera no longer exists.');
	detachCamera(document, camera.source);
	document.app.streams = document.app.streams.filter((stream) => stream !== camera);
}

/** Notes what tells a camera apart, unless its address was changed meanwhile. */
export function rememberCameraDevice(
	document: Configuration,
	id: string,
	source: string,
	device: CameraDevice
): void {
	const camera = document.app.streams.find((stream) => stream.id === id);
	if (camera?.source === source) camera.device = device;
}

/**
 * Follows cameras to the addresses they were found at, keeping their setup. Gives back the moves
 * made: not those of a camera that was changed or removed meanwhile, or that would take the
 * address of another saved camera.
 */
export function relocateCameras(document: Configuration, moves: CameraMove[]): CameraMove[] {
	return moves.filter((move) => {
		const camera = document.app.streams.find((stream) => stream.id === move.id);
		if (!camera || camera.source !== move.source) return false;
		const source = movedSource(move.source, move.host);
		if (document.app.streams.some((stream) => stream.source === source)) return false;
		keepCameraSetup(document, move.id, () => {
			camera.source = source;
			if (camera.connection)
				camera.connection.address = movedSource(camera.connection.address, move.host);
			for (const detector of document.config.detectors)
				detector.detection.source = detector.detection.source.map((item) =>
					item === move.source ? source : item
				);
		});
		return true;
	});
}

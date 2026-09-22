import path from 'node:path';
import type { CameraConnectionInput } from '../../cameras.ts';
import { DATA_DIRECTORY } from '../application-paths';
import { getFfmpegPathWithFallback } from '../ffmpeg.ts';
import { CameraChecks } from './checks.ts';
import { CameraConnectionError } from './connection.ts';
import { resolveCameraStream } from './discovery.ts';

export { discoverCameras, resolveCameraStream as getCameraConnection } from './discovery.ts';
export { CameraConnectionError } from './connection.ts';

export const cameraChecks = new CameraChecks(path.join(DATA_DIRECTORY, '.camera-checks'));

export function assertCameraCheck(checkId: string | undefined, source: string): string {
	return cameraChecks.assert(checkId, source);
}

export async function connectCamera(input: CameraConnectionInput, signal?: AbortSignal) {
	const executable = await getFfmpegPathWithFallback();
	if (!executable)
		throw new CameraConnectionError(
			'The camera software could not be found. Repair or reinstall AI Detector, then try again.'
		);
	const { source, profiles } = await resolveCameraStream(input);
	signal?.throwIfAborted();
	return cameraChecks.check(source, executable, profiles, signal);
}

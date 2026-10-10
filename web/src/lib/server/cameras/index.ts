import path from 'node:path';
import { DATA_DIRECTORY } from '../application-paths';
import { getFfmpegPathWithFallback } from '../ffmpeg.ts';
import { CameraChecks } from './checks.ts';
import { CameraConnectionError, cameraStream } from './connection.ts';

export { discoverCameras, resolveCameraStream as getCameraConnection } from './discovery.ts';
export { CameraConnectionError } from './connection.ts';

export const cameraChecks = new CameraChecks(path.join(DATA_DIRECTORY, '.camera-checks'));

export function assertCameraCheck(checkId: string | undefined, source: string): string {
	return cameraChecks.assert(checkId, source);
}

export async function connectCamera(source: string, signal?: AbortSignal) {
	const executable = await getFfmpegPathWithFallback();
	if (!executable)
		throw new CameraConnectionError(
			'The camera software could not be found. Repair or reinstall AI Detector, then try again.'
		);
	return cameraChecks.check(cameraStream(source), executable, signal);
}

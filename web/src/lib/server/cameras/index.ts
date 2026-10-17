import path from 'node:path';
import { DATA_DIRECTORY } from '../application-paths';
import { getFfmpegPathWithFallback } from '../ffmpeg.ts';
import { CameraChecks } from './checks.ts';
import { cameraSoftwareMissing, cameraStream } from './connection.ts';

export { discoverCameras, resolveCameraStream } from './discovery.ts';
export { CameraConnectionError } from './connection.ts';

export const cameraChecks = new CameraChecks(path.join(DATA_DIRECTORY, '.camera-checks'));

/** FFmpeg, which reads the cameras and plays their test recordings. */
export async function cameraSoftware(): Promise<string> {
	const executable = await getFfmpegPathWithFallback();
	if (!executable) throw cameraSoftwareMissing();
	return executable;
}

export async function connectCamera(source: string, signal?: AbortSignal) {
	const executable = await cameraSoftware();
	return cameraChecks.check(cameraStream(source), executable, signal);
}

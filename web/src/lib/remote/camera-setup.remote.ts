import { command, query } from '$app/server';
import { configuration } from '$lib/server/configuration';
import { configurationAction } from '$lib/server/configuration/request';
import { cameraSetupStatus } from '$lib/server/configuration/camera-setup';
import { detectorStatus } from '$lib/server/detector-service';
import type { RuntimeStatus } from '$lib/runtime';

function monitoringCameras(runtime: RuntimeStatus) {
	return new Set(
		runtime.phase === 'running'
			? runtime.cameras
					.filter(
						(camera) => camera.state === 'monitoring' && !camera.error && !camera.recordingError
					)
					.map((camera) => camera.id)
			: []
	);
}

export const getSetupStatus = query(() =>
	configurationAction(
		(async () => {
			const [document, runtime] = await Promise.all([configuration.read(), detectorStatus()]);
			const monitoring = monitoringCameras(runtime);
			return document.app.streams.map((camera) => ({
				...cameraSetupStatus(document, camera.id!),
				monitoring: monitoring.has(camera.id!)
			}));
		})()
	)
);

export const skipSetupAlerts = command(() => configurationAction(configuration.skipSetupAlerts()));

export const finishSetup = command(() =>
	configurationAction(
		configuration.finishSetup(async () => monitoringCameras(await detectorStatus()))
	)
);

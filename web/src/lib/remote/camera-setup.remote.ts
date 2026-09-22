import { command, query } from '$app/server';
import * as v from 'valibot';
import { configuration } from '$lib/server/configuration';
import { configurationAction } from '$lib/server/configuration/request';
import { cameraSetupStatus } from '$lib/server/configuration/camera-setup';
import { detectorStatus } from '$lib/server/detector-service';

export const getCameraSetup = query(v.string(), (id) =>
	configurationAction(
		(async () => {
			const setup = cameraSetupStatus(await configuration.read(), id);
			const runtime = await detectorStatus();
			const camera = runtime.cameras.find((item) => item.id === id);
			return {
				...setup,
				monitoring:
					runtime.phase === 'running' &&
					camera?.state === 'monitoring' &&
					!camera.error &&
					!camera.recordingError,
				monitoringMessage:
					camera?.error ?? camera?.recordingError ?? runtime.preparation ?? runtime.message
			};
		})()
	)
);

export const skipCameraAlerts = command(v.string(), (id) =>
	configurationAction(configuration.skipCameraAlerts(id))
);

export const finishCameraSetup = command(v.string(), (id) =>
	configurationAction(
		configuration.finishCameraSetup(id, async () => {
			const runtime = await detectorStatus();
			const camera = runtime.cameras.find((item) => item.id === id);
			return (
				runtime.phase === 'running' &&
				camera?.state === 'monitoring' &&
				!camera.error &&
				!camera.recordingError
			);
		})
	)
);

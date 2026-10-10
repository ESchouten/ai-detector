import { command, query } from '$app/server';
import { detectorStatus, managedDetector } from '$lib/server/detector-service';
import { SetupError } from '$lib/server/runtime-platform';

export const getRuntime = query(() => detectorStatus());

export const startDetector = command(() => {
	const detector = managedDetector();
	if (!detector)
		throw new SetupError('Use the complete application download to start detection here.');
	void detector.start();
	return detector.status();
});

export const stopDetector = command(() => {
	const detector = managedDetector();
	void detector?.stop().catch((error) => detector.fail(error));
	return detectorStatus();
});

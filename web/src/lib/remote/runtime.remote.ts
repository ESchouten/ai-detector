import { command, query } from '$app/server';
import { error } from '@sveltejs/kit';
import { detectorStatus, managedDetector } from '$lib/server/detector-service';

export const getRuntime = query(() => detectorStatus());

export const startDetector = command(() => {
	const detector = managedDetector();
	if (!detector) error(400, 'Use the complete application download to start detection here.');
	void detector.start();
	return detector.status();
});

export const stopDetector = command(() => {
	const detector = managedDetector();
	void detector?.stop().catch((error) => detector.fail(error));
	return detectorStatus();
});

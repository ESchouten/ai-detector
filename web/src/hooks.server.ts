import type { Handle, ServerInit } from '@sveltejs/kit';
import { building } from '$app/environment';
import { initializeDetector } from '$lib/server/detector-service';

export const init: ServerInit = async () => {
	if (!building) await initializeDetector();
};

export const handle: Handle = ({ event, resolve }) => {
	const disconnectSignal = event.platform?.req?.disconnectSignal;
	if (disconnectSignal)
		event.request = new Request(event.request, {
			signal: AbortSignal.any([event.request.signal, disconnectSignal])
		});
	return resolve(event);
};

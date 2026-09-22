import 'reflect-metadata';
import type { Handle } from '@sveltejs/kit';
import { building } from '$app/environment';
import { initializeDetector } from '$lib/server/detector-service';

export const handle: Handle = async ({ event, resolve }) => {
	if (!building) await initializeDetector();
	return resolve(event);
};

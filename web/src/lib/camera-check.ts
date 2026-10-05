import type { CameraConnectionResult } from './cameras.ts';

export async function checkCameraRecording(
	source: string,
	signal: AbortSignal,
	endpoint = '/camera-checks'
): Promise<CameraConnectionResult> {
	const response = await fetch(endpoint, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ source }),
		signal
	});
	if (!response.ok) {
		if (response.status === 400 || response.status === 403) {
			const { message } = await response.json();
			throw new Error(message);
		}
		throw new Error('The camera check could not finish. Please try again.');
	}
	return response.json();
}

/**
 * Check the picture of a camera that answered. The check reports the source that worked, which
 * is the one to save.
 */
export async function checkConnection<T extends { source: string }>(
	connection: T,
	signal: AbortSignal,
	endpoint?: string
): Promise<T & { check: CameraConnectionResult }> {
	signal.throwIfAborted();
	const check = await checkCameraRecording(connection.source, signal, endpoint);
	return { ...connection, source: check.source, check };
}

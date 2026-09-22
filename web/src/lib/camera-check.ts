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

import type { ClientInit, HandleClientError } from '@sveltejs/kit';
import { resolve } from '$app/paths';

// A failure in the browser leaves no trace on the computer that runs AI Detector, so it is
// reported there and ends up in the diagnostics download.
let reported = 0;
function report(cause: unknown): void {
	if (reported++ >= 10) return;
	const error = cause instanceof Error ? cause : new Error(String(cause));
	void fetch(resolve('/browser-errors'), {
		method: 'POST',
		keepalive: true,
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			message: error.message.slice(0, 1000),
			stack: (error.stack ?? '').slice(0, 6000),
			page: location.pathname.slice(0, 300)
		})
	}).catch(() => {});
}

export const init: ClientInit = () => {
	addEventListener('error', (event) => report(event.error ?? event.message));
	addEventListener('unhandledrejection', (event) => report(event.reason));
};

export const handleError: HandleClientError = ({ error }) => report(error);

import { error, redirect, type RequestEvent } from '@sveltejs/kit';
import { configuration } from './configuration';
import { DeviceAccess, localDashboard } from './device-access';

export const access = new DeviceAccess(configuration);
export const ACCESS_COOKIE = 'ai-detector-device';
export const sessionCookie = (secure: boolean) => ({
	path: '/',
	httpOnly: true,
	sameSite: 'lax' as const,
	secure,
	maxAge: 365 * 24 * 60 * 60
});

/** The local dashboard is trusted; other browsers must be paired. */
export async function authorizeRequest(event: RequestEvent): Promise<void> {
	const { request, url, cookies } = event;
	if (
		!['GET', 'HEAD', 'OPTIONS'].includes(request.method) &&
		request.headers.get('origin') !== url.origin
	)
		error(403, 'Open the dashboard directly to make changes.');
	if (
		localDashboard(
			event.platform?.req?.socket.remoteAddress ?? event.getClientAddress(),
			url,
			request
		)
	) {
		event.locals.deviceId = 'local';
		return;
	}
	const device = await access.identify(cookies.get(ACCESS_COOKIE));
	event.locals.deviceId = device?.id;
	if (!device && url.pathname !== '/pair') {
		if (request.method === 'GET' && request.headers.get('accept')?.includes('text/html'))
			redirect(303, '/pair');
		error(401, 'Connect this device to AI Detector first.');
	}
}

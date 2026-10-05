import type { Handle, HandleServerError, ServerInit } from '@sveltejs/kit';
import { building } from '$app/environment';
import { initializeDetector } from '$lib/server/detector-service';
import { startTelegramReviews } from '$lib/server/telegram-service';
import { configuration } from '$lib/server/configuration';
import { updateFollowedPresets } from '$lib/server/configuration/presets';
import { previews } from '$lib/server/preview-pool';
import { access, authorizeRequest } from '$lib/server/access';
import { webLog } from '$lib/server/web-log';
import { APP_CONFIG_PATH, DATA_DIRECTORY } from '$lib/server/application-paths';
import { negotiateLocale, SOURCE_LOCALE } from '$lib/locales';
import {
	installationLanguage,
	loadInstallationLanguage,
	runInLanguage
} from '$lib/server/request-language';

export const init: ServerInit = async () => {
	if (!building) {
		await webLog.initialize(DATA_DIRECTORY);
		await loadInstallationLanguage(APP_CONFIG_PATH);
		try {
			if (!(await access.list()).length) {
				const pairing = access.createPairing();
				console.info(
					`AI Detector initial pairing code: ${pairing.code} (valid for five minutes). Open the dashboard on this computer or enter this code on your device.`
				);
			}
		} catch (error) {
			webLog.error(
				'Could not load connected devices from app.json. Open the dashboard on this computer to recover settings.',
				error
			);
		}
		await updateFollowedPresets();
		await initializeDetector(() => configuration.read());
		startTelegramReviews();
		process.once('sveltekit:shutdown', () => previews.close());
		process.once('sveltekit:shutdown', () => webLog.flush());
	}
};

export const handleError: HandleServerError = ({ error, event }) => {
	webLog.error(
		`Request failed: ${event.request.method} ${event.route.id ?? 'unknown route'}`,
		error
	);
};

export const handle: Handle = ({ event, resolve }) => {
	// An installation has one language once set up; until then each browser gets its own.
	const requested = negotiateLocale(event.request.headers.get('accept-language'));
	const language = installationLanguage() ?? requested ?? SOURCE_LOCALE;
	return runInLanguage({ language, requested }, async () => {
		const disconnectSignal = event.platform?.req?.disconnectSignal;
		if (disconnectSignal)
			event.request = new Request(event.request, {
				signal: AbortSignal.any([event.request.signal, disconnectSignal])
			});
		await authorizeRequest(event);
		const response = await resolve(event, {
			transformPageChunk: ({ html }) => html.replace('%lang%', language)
		});
		response.headers.set('X-Frame-Options', 'DENY');
		response.headers.set('Referrer-Policy', 'same-origin');
		return response;
	});
};

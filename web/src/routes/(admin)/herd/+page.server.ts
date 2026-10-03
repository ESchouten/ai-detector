import { fail } from '@sveltejs/kit';
import { herd } from '$lib/server/herd';
import { configuration } from '$lib/server/configuration';
import { HerdError } from '$lib/server/identity-catalog';
import { readHerdPage } from '$lib/server/herd-page';
import { liveSourceKey } from '$lib/server/live-preview';
import { DATA_DIRECTORY } from '$lib/server/application-paths';
import type { Actions, PageServerLoad } from './$types';

function formText(form: FormData, name: string): string {
	return String(form.get(name) ?? '');
}

export const load: PageServerLoad = async () => {
	const [catalog, { config, app }] = await Promise.all([readHerdPage(herd), configuration.read()]);
	return {
		catalog,
		cameras: Object.fromEntries(
			(app.streams ?? []).map((camera, index) => [
				liveSourceKey(camera.source, DATA_DIRECTORY),
				camera.label || `Camera ${index + 1}`
			])
		),
		identityConfigured: config.detectors.some((detector) => detector.identity != null)
	};
};

export const actions: Actions = {
	default: async ({ request }) => {
		const form = await request.formData();
		const revision = Number(form.get('revision'));
		if (!form.has('revision') || !Number.isSafeInteger(revision) || revision < 0)
			return fail(400, { message: 'Refresh the herd and try again.' });
		const cow = formText(form, 'cow');
		const photo = formText(form, 'photo');
		const name = formText(form, 'name');
		try {
			switch (form.get('operation')) {
				case 'assign':
					await herd.assign(
						revision,
						photo,
						cow || null,
						name,
						formText(form, 'previousCow') || null
					);
					break;
				case 'rename':
					await herd.rename(revision, cow, name);
					break;
				case 'remove-example':
					await herd.removeExample(revision, cow, photo);
					break;
				case 'remove-cow':
					await herd.removeCow(revision, cow);
					break;
				case 'discard':
					await herd.discard(revision, photo);
					break;
				default:
					return fail(400, { message: 'Choose an action and try again.' });
			}
			return { saved: true };
		} catch (error) {
			if (error instanceof HerdError) return fail(error.status, { message: error.message });
			throw error;
		}
	}
};

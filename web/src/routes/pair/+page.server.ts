import { fail, redirect } from '@sveltejs/kit';
import { access, ACCESS_COOKIE, sessionCookie } from '$lib/server/access';
import { PairingError } from '$lib/server/device-access';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = ({ locals, cookies, url }) => {
	if (locals.deviceId) {
		const token = cookies.get(ACCESS_COOKIE);
		if (token) cookies.set(ACCESS_COOKIE, token, sessionCookie(url.protocol === 'https:'));
		redirect(303, '/');
	}
};

export const actions: Actions = {
	default: async ({ request, cookies, url }) => {
		const form = await request.formData();
		const code = String(form.get('code') ?? '').trim();
		try {
			const token = await access.pair(code, String(form.get('name') ?? 'Phone or computer'));
			cookies.set(ACCESS_COOKIE, token, sessionCookie(url.protocol === 'https:'));
		} catch (error) {
			if (error instanceof PairingError) return fail(400, { message: error.message });
			throw error;
		}
		redirect(303, '/');
	}
};

import { lanAddresses } from '../../../../desktop/network-addresses.ts';
import QRCode from 'qrcode';
import { fail } from '@sveltejs/kit';
import { access } from '$lib/server/access';
import type { Actions, PageServerLoad } from './$types';

const isLocal = (url: URL) => ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);

export const load: PageServerLoad = async ({ locals, url }) => ({
	devices: await access.list(),
	current: locals.deviceId,
	networks: isLocal(url) ? lanAddresses() : [],
	encrypted: url.protocol === 'https:'
});

export const actions: Actions = {
	connect: async ({ url, request }) => {
		const destination = new URL('/pair', url);
		if (isLocal(url)) {
			const form = await request.formData();
			const networks = lanAddresses();
			const selected = form.get('address');
			const address = selected
				? networks.find((network) => network.address === selected)
				: networks[0];
			if (!address)
				return fail(400, { message: 'Connect this computer to your local network and try again.' });
			destination.hostname = address.address;
		}
		const pairing = access.createPairing();
		destination.hash = new URLSearchParams({ code: pairing.code }).toString();
		return {
			...pairing,
			link: destination.href,
			qr: await QRCode.toDataURL(destination.href, { margin: 1, width: 256 })
		};
	},
	remove: async ({ request, locals }) => {
		const form = await request.formData();
		const id = String(form.get('id') ?? '');
		if (id === locals.deviceId)
			return fail(400, { message: 'Use another connected device to remove this browser.' });
		await access.revoke(id);
		return { removed: true };
	}
};

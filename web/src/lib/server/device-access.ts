import { createHash, randomBytes, randomInt, randomUUID } from 'node:crypto';
import type { PairedDevice } from '../schema.ts';
import type { ConfigurationStore } from './configuration/store.ts';

const YEAR = 365 * 24 * 60 * 60 * 1000;
export class PairingError extends Error {}
const hash = (token: string) => createHash('sha256').update(token).digest('hex');

/** One local access list. The browser holds the token; disk holds only its hash. */
export class DeviceAccess {
	private pairing?: { code: string; expires: number; attempts: number };
	private settings: Pick<ConfigurationStore, 'readDevices' | 'updateDevices'>;
	private now: () => number;

	constructor(settings: Pick<ConfigurationStore, 'readDevices' | 'updateDevices'>, now = Date.now) {
		this.settings = settings;
		this.now = now;
	}

	async identify(token: string | undefined): Promise<PairedDevice | undefined> {
		if (!token) return;
		const digest = hash(token);
		return (await this.settings.readDevices()).find(
			(device) => device.hash === digest && device.expires > this.now()
		);
	}

	async list(): Promise<Omit<PairedDevice, 'hash'>[]> {
		return (await this.settings.readDevices())
			.filter((device) => device.expires > this.now())
			.map(({ id, name, created, expires }) => ({ id, name, created, expires }));
	}

	createPairing(): { code: string; expires: number } {
		this.pairing = {
			code: randomInt(1000000).toString().padStart(6, '0'),
			expires: this.now() + 5 * 60 * 1000,
			attempts: 0
		};
		return { code: this.pairing.code, expires: this.pairing.expires };
	}

	async pair(code: string, name: string): Promise<string> {
		const pairing = this.pairing;
		if (!pairing || pairing.expires <= this.now() || pairing.attempts >= 10)
			throw new PairingError('This code has expired. Create a new code on a connected device.');
		pairing.attempts++;
		if (code !== pairing.code)
			throw new PairingError('The code did not match. Check the six digits and try again.');
		this.pairing = undefined;
		return this.register(name);
	}

	private async register(name: string): Promise<string> {
		const token = randomBytes(32).toString('base64url');
		await this.settings.updateDevices((saved) => {
			const devices = saved.filter((device) => device.expires > this.now());
			if (devices.length >= 50)
				throw new PairingError('Remove an old connected device before adding another.');
			return [
				...devices,
				{
					id: randomUUID(),
					name: name.trim().slice(0, 80) || 'Browser',
					hash: hash(token),
					created: this.now(),
					expires: this.now() + YEAR
				}
			];
		});
		return token;
	}

	revoke(id: string): Promise<void> {
		return this.settings.updateDevices((devices) => devices.filter((device) => device.id !== id));
	}
}

export function localDashboard(peer: string, url: URL, request: Request): boolean {
	return (
		['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(peer) &&
		['localhost', '127.0.0.1', '[::1]'].includes(url.hostname) &&
		!['cross-site', 'same-site'].includes(request.headers.get('sec-fetch-site') ?? '') &&
		(!request.headers.has('origin') || request.headers.get('origin') === url.origin)
	);
}

import { Bonjour } from 'bonjour-service';
import { hostname, networkInterfaces } from 'node:os';

/** LAN discovery is optional; a multicast failure must not stop local monitoring. */
export function advertiseDashboard(port: number): () => void {
	const name = hostname().replace(/\.$/, '');
	const host = name.toLowerCase().endsWith('.local') ? name : `${name}.local`;
	const suffix = port === 80 ? '' : `:${port}`;
	for (const entry of Object.values(networkInterfaces()).flat()) {
		if (entry?.family === 'IPv4' && !entry.internal && !entry.address.startsWith('169.254.'))
			console.info(`LAN URL: http://${entry.address}${suffix}`);
	}
	const bonjour = new Bonjour(undefined, (error: Error) =>
		console.warn('LAN discovery unavailable:', error)
	);
	const service = bonjour.publish({ name: `AI Detector on ${name}`, host, type: 'http', port });
	service.on('up', () => console.info(`LAN name: http://${host}${suffix}`));
	return () => bonjour.unpublishAll(() => bonjour.destroy());
}

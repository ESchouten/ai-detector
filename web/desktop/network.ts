import ciao from '@homebridge/ciao';
import { lanAddresses } from './network-addresses.ts';

/** LAN discovery is optional; a multicast failure must not stop local monitoring. */
export function advertiseDashboard(port: number): () => Promise<void> {
	const suffix = port === 80 ? '' : `:${port}`;
	for (const { address } of lanAddresses()) console.info(`LAN URL: http://${address}${suffix}`);
	const responder = ciao.getResponder();
	// Ciao probes this application name and renames it on conflicts; the OS
	// remains responsible for the computer's own hostname.
	const service = responder.createService({
		name: 'AI Detector',
		hostname: 'ai-detector',
		type: 'http',
		port,
		disabledIpv6: true
	});
	const logAddress = () =>
		console.info(`LAN name: http://${service.getHostname().replace(/\.$/, '')}${suffix}`);
	service.on('hostname-change', logAddress);
	service
		.advertise()
		.then(logAddress)
		.catch((error) => console.warn('LAN discovery unavailable:', error));
	return () =>
		responder.shutdown().catch((error) => console.warn('LAN discovery shutdown failed:', error));
}

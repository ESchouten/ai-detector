import { networkInterfaces } from 'node:os';

const VIRTUAL =
	/^(?:docker|veth|br[-\d]|bridge\d|virbr|vmnet|vboxnet|utun|tun|tap|wg\d|tailscale|vEthernet)|VPN|Virtual|WSL/i;
const PHYSICAL = /^(?:en\d|eth\d|wlan\d|en[opsx]|wl[px]|Wi-?Fi|Ethernet)/i;
const PRIVATE_IP = /^(?:10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)/;

/** Local-network candidates for desktop links and pairing. Multiple NICs remain selectable. */
export function lanAddresses(
	interfaces = networkInterfaces()
): { name: string; address: string }[] {
	const candidates = Object.entries(interfaces)
		.flatMap(([name, entries]) =>
			VIRTUAL.test(name)
				? []
				: (entries ?? [])
						.filter(
							(entry) =>
								entry.family === 'IPv4' && !entry.internal && PRIVATE_IP.test(entry.address)
						)
						.map(({ address }) => ({ name, address }))
		)
		.sort(
			(a, b) =>
				Number(PHYSICAL.test(b.name)) - Number(PHYSICAL.test(a.name)) ||
				a.name.localeCompare(b.name)
		);
	return candidates.filter(
		(entry, index) => candidates.findIndex(({ address }) => address === entry.address) === index
	);
}

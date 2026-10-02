import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { NetworkInterfaceInfo } from 'node:os';
import { lanAddresses } from './network-addresses.ts';

const nic = (address: string, internal = false): NetworkInterfaceInfo[] => [
	{
		address,
		internal,
		family: 'IPv4',
		netmask: '255.255.255.0',
		mac: '00:00:00:00:00:00',
		cidr: `${address}/24`
	}
];

test('LAN links exclude Docker, WSL and VPN adapters on Windows, macOS and Linux', () => {
	for (const virtual of [
		'vEthernet (WSL)',
		'docker0',
		'br-abcdef',
		'bridge100',
		'br0',
		'utun4',
		'Example VPN',
		'wg0'
	]) {
		assert.deepEqual(lanAddresses({ [virtual]: nic('172.20.0.1'), 'Wi-Fi': nic('192.168.1.20') }), [
			{ name: 'Wi-Fi', address: '192.168.1.20' }
		]);
	}
});

test('multiple local networks remain available; physical adapters are preferred and addresses deduplicated', () => {
	assert.deepEqual(
		lanAddresses({
			mystery: nic('10.2.0.5'),
			lo0: nic('127.0.0.1', true),
			en0: nic('192.168.1.20'),
			eth0: nic('10.1.0.5'),
			duplicate: nic('192.168.1.20'),
			disconnected: nic('169.254.1.1')
		}),
		[
			{ name: 'en0', address: '192.168.1.20' },
			{ name: 'eth0', address: '10.1.0.5' },
			{ name: 'mystery', address: '10.2.0.5' }
		]
	);
	assert.deepEqual(lanAddresses({ lo: nic('127.0.0.1', true), docker0: nic('172.20.0.1') }), []);
});

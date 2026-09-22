import assert from 'node:assert/strict';
import { test } from 'node:test';
import { cameraDraftAddress, cameraEditConnection } from '../src/lib/cameras.ts';

test('camera drafts retain ordinary device addresses and ONVIF paths', () => {
	for (const address of [
		'192.168.1.20',
		'barn-camera.local:8080',
		'http://192.168.1.20/onvif/device_service',
		'https://[2001:db8::1]:8443/onvif/device_service'
	])
		assert.equal(cameraDraftAddress(address), address);
});

test('changing a saved camera login reuses its address and username without exposing its password', () => {
	assert.deepEqual(
		cameraEditConnection('rtsp://farm%40home:private%23%2F%3F@camera.local:554/stream'),
		{
			username: 'farm@home',
			streamUri: 'rtsp://camera.local:554/stream'
		}
	);
	assert.deepEqual(cameraEditConnection('invalid'), { username: '', streamUri: '' });
});

test('pasted credentials, tokens and invalid addresses are omitted from serialized drafts', () => {
	for (const address of [
		'http://farmer:private@camera.local/onvif/device_service',
		'farmer:private@camera.local',
		'http://farmer@camera.local',
		'rtsp://farmer:private@camera.local/live',
		'http://camera.local?token=private',
		'http://camera.local#private',
		'http://farmer:private@',
		'http://['
	]) {
		const draft = {
			label: 'Barn',
			address: cameraDraftAddress(address),
			preset: 'copy',
			copyFromCameraId: 'existing-camera'
		};
		assert.deepEqual(JSON.parse(JSON.stringify(draft)), {
			label: 'Barn',
			preset: 'copy',
			copyFromCameraId: 'existing-camera'
		});
	}
});

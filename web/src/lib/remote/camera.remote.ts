import { command } from '$app/server';
import { cameraConnectionInput } from '$lib/cameras';
import {
	discoverCameras as discover,
	getCameraConnection as resolveConnection
} from '$lib/server/cameras';
import { configurationAction } from '$lib/server/configuration/request';

export const discoverCameras = command(() => discover());

export const getCameraConnection = command(cameraConnectionInput, (input) =>
	configurationAction(resolveConnection(input))
);

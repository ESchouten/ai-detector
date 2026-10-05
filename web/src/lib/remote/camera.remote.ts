import { command, query } from '$app/server';
import * as v from 'valibot';
import { cameraConnectionInput } from '$lib/cameras';
import { cameraInput, sameTelegram } from '$lib/configuration';
import {
	assertCameraCheck,
	discoverCameras as discover,
	getCameraConnection as resolveConnection
} from '$lib/server/cameras';
import { configuration } from '$lib/server/configuration';
import { cameraSetupStatus } from '$lib/server/configuration/camera-setup';
import { configurationAction } from '$lib/server/configuration/request';

export const discoverCameras = command(() => discover());

export const getCameraConnection = command(cameraConnectionInput, (input) =>
	configurationAction(() => resolveConnection(input))
);

export const getCameras = query(async () => {
	const { app, config } = await configuration.read();
	return app.streams.map((camera) => {
		const rules = config.detectors.flatMap((detector, index) =>
			detector.detection.source.includes(camera.source)
				? [{ detector, meta: app.detectors[index] }]
				: []
		);
		return {
			...camera,
			setupComplete: !!cameraSetupStatus({ app, config }, camera.id!).completedAt,
			id: camera.id!,
			label: camera.label ?? 'Camera',
			monitored: rules.length > 0,
			rules: rules.map(({ meta }) => meta),
			alerts: app.telegrams
				.filter((channel) =>
					rules.some(({ detector }) =>
						detector.exporters?.telegram?.some((item) => sameTelegram(item, channel))
					)
				)
				.map(({ label }) => label)
		};
	});
});

export const saveCamera = command(cameraInput, (input) =>
	configurationAction(async () => {
		const existing = input.id
			? (await configuration.read()).app.streams.find((camera) => camera.id === input.id)
			: undefined;
		const verifiedAt =
			input.checkId || !existing || existing.source !== input.source
				? assertCameraCheck(input.checkId, input.source)
				: undefined;
		return configuration.saveCamera(input, verifiedAt);
	})
);

export const removeCamera = command(v.string(), (id) =>
	configurationAction(() => configuration.removeCamera(id))
);

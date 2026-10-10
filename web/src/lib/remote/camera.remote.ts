import { command, query } from '$app/server';
import * as v from 'valibot';
import { cameraConnectionInput } from '$lib/cameras';
import { cameraInput, sameTelegram } from '$lib/configuration';
import {
	assertCameraCheck,
	discoverCameras as discover,
	getCameraConnection as resolveConnection
} from '$lib/server/cameras';
import type { CameraHistory } from '$lib/camera-history';
import { DATA_DIRECTORY } from '$lib/server/application-paths';
import { managedDetector, watchHistory } from '$lib/server/detector-service';
import { recordings } from '$lib/server/recordings';
import { sourceKey } from '$lib/server/source-key';
import { configuration } from '$lib/server/configuration';
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

/** When each camera was watched and what it recorded, over the last hour, day or week. */
export const getCameraHistory = query(v.picklist([1, 24, 168]), async (hours) => {
	const to = new Date();
	const from = new Date(to.getTime() - hours * 3600000);
	const [{ app }, watched, detections] = await Promise.all([
		configuration.read(),
		watchHistory.read(from, to),
		recordings.between(from, to)
	]);
	const cameras: CameraHistory[] = app.streams.map((camera) => {
		const key = sourceKey(camera.source, DATA_DIRECTORY).slice(0, 12);
		return {
			id: camera.id!,
			label: camera.label ?? 'Camera',
			stretches: watched.get(camera.id!) ?? [],
			detections: detections.filter((detection) => detection.camera === key)
		};
	});
	const placed = new Set(cameras.flatMap((camera) => camera.detections));
	return {
		from: from.toISOString(),
		to: to.toISOString(),
		/** Without a detector of its own this server cannot tell when cameras were watched. */
		recorded: managedDetector() !== null,
		cameras,
		/** Recordings of a camera that has since been removed or changed, or from before cameras were kept. */
		others: detections.filter((detection) => !placed.has(detection))
	};
});

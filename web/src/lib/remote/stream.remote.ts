import { configurationAction } from '$lib/server/configuration/request';
import { command, form, query } from '$app/server';
import { redirect } from '@sveltejs/kit';
import * as v from 'valibot';
import { configuration } from '$lib/server/configuration';
import {
	cameraInput,
	streamInput,
	streamMeta,
	streamOrder,
	sameTelegram
} from '$lib/configuration';
import { assertCameraCheck } from '$lib/server/cameras';
import { cameraSetupStatus } from '$lib/server/configuration/camera-setup';

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

export const getCamera = query(v.string(), async (id) => {
	const { app, config } = await configuration.read();
	const camera = app.streams.find((item) => item.id === id);
	if (!camera) return undefined;
	return {
		...camera,
		id: camera.id!,
		monitored: config.detectors.some((detector) =>
			detector.detection.source.includes(camera.source)
		)
	};
});

export const saveCamera = command(cameraInput, async (input) => {
	return configurationAction(
		(async () => {
			const existing = input.id
				? (await configuration.read()).app.streams.find((camera) => camera.id === input.id)
				: undefined;
			const verifiedAt =
				input.checkId || !existing || existing.source !== input.source
					? assertCameraCheck(input.checkId, input.source)
					: undefined;
			return configuration.saveCamera(input, verifiedAt);
		})()
	);
});

export const removeCamera = command(v.string(), (id) =>
	configurationAction(configuration.removeCamera(id))
);

export const getStreams = query(async () => {
	const { app } = await configuration.read();
	return app.streams.map((stream, index) => ({
		...stream,
		label: stream.label ?? 'Stream ' + (index + 1)
	}));
});

export const saveStream = form(streamInput, async (input) => {
	await configurationAction(configuration.saveStream(input));
	redirect(
		302,
		input.next?.startsWith('/') && !input.next.startsWith('//') ? input.next : '/streams'
	);
});

export const deleteStream = command(v.pick(streamMeta, ['source']), ({ source }) =>
	configurationAction(configuration.deleteStream(source))
);
export const reorderStream = command(streamOrder, ({ index0, index1 }) =>
	configurationAction(configuration.reorderStream(index0, index1))
);

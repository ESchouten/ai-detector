import { configurationAction } from '$lib/server/configuration/request';
import { command, form, query } from '$app/server';
import { redirect } from '@sveltejs/kit';
import * as v from 'valibot';
import { configuration } from '$lib/server/configuration';
import { streamInput, streamMeta, streamOrder } from '$lib/configuration';

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

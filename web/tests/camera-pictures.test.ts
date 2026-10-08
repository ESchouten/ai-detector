import assert from 'node:assert/strict';
import { test } from 'node:test';
import { setTimeout as delay } from 'node:timers/promises';
import { CameraPictures, PictureRecords, pictureRecord } from '../src/lib/camera-pictures.ts';
import { createPictureStream } from '../src/lib/server/camera-pictures.ts';

const jpeg = (text: string) => new TextEncoder().encode(text);
const text = (bytes: Uint8Array) => new TextDecoder().decode(bytes);

test('records survive being cut anywhere on the way', () => {
	const sent = Buffer.concat([
		pictureRecord('barn', jpeg('first picture')),
		pictureRecord('calving-pen', jpeg('')),
		pictureRecord('barn', jpeg('second'))
	]);
	for (let cut = 1; cut < sent.length; cut++) {
		const records = new PictureRecords();
		const received = [...records.read(sent.subarray(0, cut)), ...records.read(sent.subarray(cut))];
		assert.deepEqual(
			received.map(({ id, picture }) => [id, text(picture)]),
			[
				['barn', 'first picture'],
				['calving-pen', ''],
				['barn', 'second']
			],
			`cut at ${cut}`
		);
	}
});

/** A camera that gives the pictures it is told to, then ends or fails. */
function camera(pictures: string[], failure?: Error) {
	return new ReadableStream<Uint8Array>({
		pull(controller) {
			const next = pictures.shift();
			if (next !== undefined) controller.enqueue(jpeg(next));
			else if (failure) controller.error(failure);
			else controller.close();
		}
	});
}

test('several cameras share one stream, and each one says when it has ended', async () => {
	const sources: Record<string, ReadableStream<Uint8Array>> = {
		'rtsp://barn': camera(['barn 1', 'barn 2']),
		'rtsp://pen': camera(['pen 1'], new Error('Live stream ended.'))
	};
	const stream = createPictureStream(
		[
			{ id: 'barn', source: 'rtsp://barn' },
			{ id: 'pen', source: 'rtsp://pen' }
		],
		(source) => sources[source],
		new AbortController().signal
	);
	const records = new PictureRecords();
	const received: Record<string, string[]> = { barn: [], pen: [] };
	const reader = stream.getReader();
	for (let next = await reader.read(); !next.done; next = await reader.read())
		for (const { id, picture } of records.read(next.value)) received[id].push(text(picture));
	assert.deepEqual(received, { barn: ['barn 1', 'barn 2', ''], pen: ['pen 1', ''] });
});

test('a browser that leaves ends every camera of its stream', async () => {
	const opened: AbortSignal[] = [];
	const leave = new AbortController();
	const reader = createPictureStream(
		[
			{ id: 'barn', source: 'rtsp://barn' },
			{ id: 'pen', source: 'rtsp://pen' }
		],
		(_source, signal) => {
			opened.push(signal);
			return new ReadableStream<Uint8Array>({
				start(controller) {
					controller.enqueue(jpeg('picture'));
					signal.addEventListener('abort', () => controller.close());
				}
			});
		},
		leave.signal
	).getReader();
	assert.ok((await reader.read()).value);
	leave.abort();
	while (!(await reader.read()).done);
	assert.deepEqual(
		opened.map((signal) => signal.aborted),
		[true, true]
	);
});

/** The page's side: what was asked of the server, and a way to answer each request. */
function server() {
	const requests: { url: string; signal: AbortSignal; send: (chunk: Uint8Array) => void }[] = [];
	const read = async (url: string, signal: AbortSignal) =>
		new ReadableStream<Uint8Array>({
			start(controller) {
				requests.push({ url, signal, send: (chunk) => controller.enqueue(chunk) });
				signal.addEventListener('abort', () => controller.error(new Error('aborted')));
			}
		});
	return { requests, read };
}

test('a page uses one connection for all its cameras and asks again when they change', async () => {
	const { requests, read } = server();
	const pictures = new CameraPictures(() => '/cameras/pictures', read);
	const seen: Record<string, (string | null)[]> = { barn: [], pen: [] };
	const leaveBarn = pictures.subscribe('barn', (url) => seen.barn.push(url));
	pictures.subscribe('pen', (url) => seen.pen.push(url));
	await delay(0);
	assert.deepEqual(
		requests.map(({ url }) => url),
		['/cameras/pictures?camera=barn&camera=pen']
	);

	requests[0].send(pictureRecord('barn', jpeg('barn 1')));
	requests[0].send(pictureRecord('barn', jpeg('barn 2')));
	await delay(0);
	assert.equal(seen.barn.length, 2);
	assert.equal(await (await fetch(seen.barn[1]!)).text(), 'barn 2');
	// The picture that was replaced is released again.
	await assert.rejects(fetch(seen.barn[0]!));
	assert.deepEqual(seen.pen, []);

	leaveBarn();
	await delay(0);
	assert.equal(requests[0].signal.aborted, true);
	assert.equal(requests[1].url, '/cameras/pictures?camera=pen');
	// The camera that stays is not told that its stream ended.
	assert.deepEqual(seen.pen, []);
});

test('a camera whose stream ended is asked for again when someone tries again', async () => {
	const { requests, read } = server();
	const pictures = new CameraPictures(() => '/cameras/pictures', read);
	const seen: (string | null)[] = [];
	const leave = pictures.subscribe('barn', (url) => seen.push(url));
	await delay(0);
	requests[0].send(pictureRecord('barn', new Uint8Array(0)));
	await delay(0);
	assert.deepEqual([...seen], [null]);

	leave();
	pictures.subscribe('barn', (url) => seen.push(url));
	await delay(0);
	assert.equal(requests.length, 2);
});

import { pictureRecord } from '../camera-pictures.ts';

type Open = (source: string, signal: AbortSignal) => ReadableStream<Uint8Array>;

/**
 * The pictures of several cameras as one stream of records. A browser that falls behind makes
 * each camera skip pictures instead of queueing them.
 */
export function createPictureStream(
	cameras: { id: string; source: string }[],
	open: Open,
	signal: AbortSignal
): ReadableStream<Uint8Array> {
	const closed = new AbortController();
	const ended = AbortSignal.any([signal, closed.signal]);
	let wanted: (() => void) | undefined;
	let finished = false;
	return new ReadableStream<Uint8Array>(
		{
			start(controller) {
				let remaining = cameras.length;
				const follow = async ({ id, source }: { id: string; source: string }) => {
					const reader = open(source, ended).getReader();
					try {
						while (true) {
							const { value, done } = await reader.read();
							if (done) break;
							controller.enqueue(pictureRecord(id, value));
							if ((controller.desiredSize ?? 0) <= 0)
								await new Promise<void>((resolve) => {
									const previous = wanted;
									wanted = () => {
										previous?.();
										resolve();
									};
								});
						}
					} catch {
						// The camera's stream failed; the empty record below says that it ended.
					}
					if (ended.aborted) return;
					controller.enqueue(pictureRecord(id, new Uint8Array(0)));
					if (--remaining === 0 && !finished) {
						finished = true;
						controller.close();
					}
				};
				ended.addEventListener(
					'abort',
					() => {
						wanted?.();
						if (finished || closed.signal.aborted) return;
						finished = true;
						controller.close();
					},
					{ once: true }
				);
				for (const camera of cameras) void follow(camera);
			},
			pull() {
				const waiting = wanted;
				wanted = undefined;
				waiting?.();
			},
			cancel() {
				closed.abort();
			}
		},
		{ highWaterMark: 1 }
	);
}

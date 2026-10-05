import type { CameraProfile, DiscoveredCamera, CameraConnectionResult } from './cameras.ts';
import type { StreamMeta } from './schema.ts';
import { errorMessage } from './remote-errors.ts';

export interface CameraLogin {
	username: string;
	password: string;
}

/** A camera that answered: the stream to use, its other streams, and how to find it again. */
export interface CameraConnection {
	source: string;
	profiles: CameraProfile[];
	connection?: StreamMeta['connection'];
}

/** A connection whose picture was checked. */
export interface CheckedConnection extends CameraConnection {
	check: CameraConnectionResult;
	/** The login that reached a camera found on the network. A stream entered by hand has none. */
	login?: CameraLogin;
}

interface ListedCamera extends DiscoveredCamera {
	/** The last connection that showed a picture; it stays on screen while the camera is tried again. */
	connection?: CheckedConnection;
}

/** A camera on its way into the installation. Each state carries what its next step needs. */
export type BatchCamera =
	| (ListedCamera & { state: 'waiting' | 'connecting'; error?: undefined })
	| (ListedCamera & { state: 'failed'; error: string })
	| (ListedCamera & { state: 'ready'; connection: CheckedConnection; error?: string })
	| (ListedCamera & {
			state: 'saved';
			connection: CheckedConnection;
			savedId: string;
			error?: undefined;
	  });

/** Connect cameras with bounded concurrency, preserving successful results on retry. */
export async function connectCameraBatch(
	cameras: BatchCamera[],
	login: CameraLogin,
	connect: (input: CameraLogin & { address: string }) => Promise<CheckedConnection>,
	update: (camera: BatchCamera) => void,
	signal: AbortSignal
): Promise<void> {
	const pending = cameras.filter(
		(camera) => camera.state === 'waiting' || camera.state === 'failed'
	);
	let next = 0;
	async function worker() {
		while (!signal.aborted && next < pending.length) {
			const camera = pending[next++];
			update({ ...camera, state: 'connecting', error: undefined });
			try {
				const connection = await connect({ address: camera.address, ...login });
				if (signal.aborted) return;
				update({
					...camera,
					state: 'ready',
					connection: { ...connection, login: { ...login } },
					error: undefined
				});
			} catch (cause) {
				if (signal.aborted) return;
				update({
					...camera,
					state: 'failed',
					error: errorMessage(cause, 'Could not connect. Check this camera’s login and network.')
				});
			}
		}
	}
	await Promise.all(Array.from({ length: Math.min(2, pending.length) }, worker));
}

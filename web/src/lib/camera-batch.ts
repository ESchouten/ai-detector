import type { CameraProfile, DiscoveredCamera } from './cameras.ts';
import type { StreamMeta } from './schema.ts';
import { errorMessage } from './remote-errors.ts';

export interface CameraLogin {
	username: string;
	password: string;
}

export interface BatchConnection {
	source: string;
	profiles: CameraProfile[];
	connection?: StreamMeta['connection'];
}

export interface BatchCamera extends DiscoveredCamera {
	state: 'waiting' | 'connecting' | 'ready' | 'failed' | 'saved' | 'skipped';
	connection?: BatchConnection;
	login?: CameraLogin;
	profileToken?: string;
	savedId?: string;
	error?: string;
}

/** Resolve logins only. Every camera still needs its own recording check and explicit save. */
export async function connectCameraBatch(
	cameras: BatchCamera[],
	login: CameraLogin,
	connect: (input: CameraLogin & { address: string }) => Promise<BatchConnection>,
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
				update({ ...camera, state: 'ready', connection, login: { ...login }, error: undefined });
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

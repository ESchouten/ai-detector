import type { CameraRuntimeStatus, RuntimeStatus } from './runtime.ts';

export type CameraTone = 'neutral' | 'ok' | 'warn' | 'bad';

export function cameraStatusBadge(
	camera: CameraRuntimeStatus | undefined,
	runtime: Pick<RuntimeStatus, 'managed' | 'readiness'>,
	stale: boolean
): { label: string; tone: CameraTone } {
	if (stale || !runtime.managed) return { label: 'Status unavailable', tone: 'warn' };
	if (runtime.readiness === 'idle') return { label: 'Paused', tone: 'neutral' };
	if (runtime.readiness === 'failed') return { label: 'Detection stopped', tone: 'bad' };
	if (!camera) return { label: 'Preparing', tone: 'neutral' };
	if (camera.state === 'paused') return { label: 'Paused', tone: 'neutral' };
	if (camera.state === 'failed') return { label: 'Detection stopped', tone: 'bad' };
	if (camera.state === 'offline') return { label: 'Camera offline', tone: 'bad' };
	if (camera.recordingError) return { label: 'Recording failed', tone: 'bad' };
	if (camera.error) return { label: 'Detection delayed', tone: 'warn' };
	if (camera.state === 'monitoring') return { label: 'Monitoring', tone: 'ok' };
	return {
		label: camera.state === 'connecting' ? 'Connecting' : 'Preparing',
		tone: 'neutral'
	};
}

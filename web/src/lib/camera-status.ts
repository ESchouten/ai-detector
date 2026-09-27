import type { CameraRuntimeStatus, RuntimeStatus } from './runtime.ts';

export function cameraStatusBadge(
	camera: CameraRuntimeStatus | undefined,
	runtime: Pick<RuntimeStatus, 'managed' | 'readiness'>,
	stale: boolean
): { label: string; variant: 'secondary' | 'success' | 'warning' | 'destructive' } {
	if (stale || !runtime.managed) return { label: 'Status unavailable', variant: 'warning' };
	if (runtime.readiness === 'idle') return { label: 'Paused', variant: 'secondary' };
	if (runtime.readiness === 'failed') return { label: 'Detection stopped', variant: 'destructive' };
	if (!camera) return { label: 'Preparing', variant: 'secondary' };
	if (camera.state === 'paused') return { label: 'Paused', variant: 'secondary' };
	if (camera.state === 'failed') return { label: 'Detection stopped', variant: 'destructive' };
	if (camera.state === 'offline') return { label: 'Camera offline', variant: 'destructive' };
	if (camera.recordingError) return { label: 'Recording failed', variant: 'destructive' };
	if (camera.error) return { label: 'Detection delayed', variant: 'warning' };
	if (camera.state === 'monitoring') return { label: 'Monitoring', variant: 'success' };
	return {
		label: camera.state === 'connecting' ? 'Connecting' : 'Preparing',
		variant: 'secondary'
	};
}

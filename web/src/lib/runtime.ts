export type RuntimePhase = 'stopped' | 'checking' | 'starting' | 'running' | 'stopping' | 'failed';
export type RuntimeReadiness =
	| 'idle'
	| 'preparing'
	| 'connecting'
	| 'monitoring'
	| 'degraded'
	| 'failed';

export interface CameraRuntimeStatus {
	id: string;
	label: string;
	sourceKey: string;
	state: 'connecting' | 'receiving' | 'monitoring' | 'offline' | 'failed' | 'paused';
	lastFrameAt: string | null;
	lastProcessedAt: string | null;
	lastInferenceAt: string | null;
	lastRecordingAt: string | null;
	error?: string;
	recordingError?: string;
}

export interface RuntimeStatus {
	managed: boolean;
	phase: RuntimePhase;
	message: string;
	helpUrl?: string;
	dataDirectory: string;
	readiness: RuntimeReadiness;
	cameras: CameraRuntimeStatus[];
	preparation?: string;
	notice?: string;
	issues?: string[];
	backends?: { label: string; engine: string }[];
	storageWarning?: string;
}

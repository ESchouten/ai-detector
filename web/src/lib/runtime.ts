export type RuntimeMode = 'auto' | 'native' | 'docker';
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
	mode: RuntimeMode;
	selected: 'native' | 'docker' | null;
	phase: RuntimePhase;
	message: string;
	helpUrl?: string;
	logs: string;
	dataDirectory: string;
	readiness: RuntimeReadiness;
	cameras: CameraRuntimeStatus[];
	preparation?: string;
	notice?: string;
}
